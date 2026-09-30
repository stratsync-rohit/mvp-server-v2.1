"""Tests for the controlled notification-send API."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.schemas.destination import Destination
from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
from src.services.notification_service import NotificationService


DESTINATION_ID = "tenant-1:team-1:channel-1"
RISK_ID = "RISK-001"


def _destination(*, active: bool = True, reference: dict | None = None) -> Destination:
    """Build a trusted destination fixture."""
    return Destination(
        destination_id=DESTINATION_ID,
        tenant_id="tenant-1",
        team_id="team-1",
        channel_id="channel-1",
        is_active=active,
        conversation_reference=reference or {"conversation": {"id": "channel-1"}},
    )


class DestinationServiceDouble:
    """Destination lookup double that records the requested ID."""

    def __init__(self, destination: Destination | None):
        self.destination = destination
        self.lookups = []

    async def get(self, destination_id: str):
        self.lookups.append(destination_id)
        return self.destination


class NotificationRepositoryDouble:
    """Notification persistence double recording lifecycle transitions."""

    def __init__(self):
        self.created = []
        self.sent = []
        self.failed = []

    async def create(self, notification):
        self.created.append(notification)

    async def mark_sent(self, notification_id, message_id):
        self.sent.append((notification_id, message_id))

    async def mark_failed(self, notification_id, error):
        self.failed.append((notification_id, error))


class ConversationClientDouble:
    """Outbound provider double."""

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result if result is not None else {"id": "teams-message-1"}
        self.error = error
        self.calls = []

    async def send_activity(self, reference, card):
        self.calls.append((reference, card))
        if self.error:
            raise self.error
        return self.result


class RiskServiceDouble:
    """Risk lookup double returning database-owned content."""

    def __init__(self, risk=None):
        self.risk = risk or {
            "risk_id": RISK_ID,
            "is_active": True,
            "severity": "high",
            "title": "Database Risk Title",
            "subtitle": "Database Risk Subtitle",
            "summary": "Database Risk Summary",
            "views": {"notification": {"blocks": []}},
        }
        self.lookups = []

    async def get(self, risk_id):
        self.lookups.append(risk_id)
        return self.risk


def _app(service: NotificationService, risk_service=None, renderer=None):
    """Create an app with notification dependencies overridden."""
    app = create_app()
    app.state.container = Container(
        adapter=object(),
        bot=object(),
        notification_service=service,
        risk_service=risk_service or RiskServiceDouble(),
        risk_card_renderer=renderer or TeamsRiskCardRenderer(),
    )
    return app


def test_public_routes_include_only_the_nine_expected_routes():
    app = create_app()
    routes = sorted(
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path.startswith("/api/") or route.path in {"/health", "/ready"}
    )

    assert routes == [
        ("GET", "/api/installations"),
        ("GET", "/api/notifications"),
        ("GET", "/api/notifications/{notification_id}"),
        ("GET", "/api/notifications/{notification_id}/reactions"),
        ("GET", "/health"),
        ("GET", "/ready"),
        ("POST", "/api/destinations/resolve"),
        ("POST", "/api/messages"),
        ("POST", "/api/notifications/send"),
    ]


def test_valid_send_renders_database_risk_and_returns_safe_metadata():
    risk_service = RiskServiceDouble()
    destination_service = DestinationServiceDouble(
        _destination(reference={"conversation": {"id": "channel-1"}, "secret": "hidden"})
    )
    repository = NotificationRepositoryDouble()
    conversation_client = ConversationClientDouble()
    service = NotificationService(repository, destination_service, conversation_client)

    response = TestClient(_app(service, risk_service=risk_service)).post(
        "/api/notifications/send",
        json={
            "destination_id": DESTINATION_ID,
            "risk_id": RISK_ID,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["destination_id"] == DESTINATION_ID
    assert body["data"]["status"] == "sent"
    assert risk_service.lookups == [RISK_ID]
    assert destination_service.lookups == [DESTINATION_ID]
    assert repository.created[0]["status"] == "pending"
    assert repository.created[0]["risk_id"] == "RISK-001"
    assert repository.created[0]["tenant_id"] == "tenant-1"
    assert repository.created[0]["team_id"] == "team-1"
    assert repository.created[0]["channel_id"] == "channel-1"
    card_body = conversation_client.calls[0][1]["content"]["body"]
    assert {item["text"] for item in card_body[:4]} == {
        "HIGH", "Database Risk Title", "Database Risk Subtitle", "Database Risk Summary"
    }
    assert repository.sent == [(body["data"]["notification_id"], "teams-message-1")]


def test_request_rejects_client_supplied_risk_content_and_routing_metadata():
    repository = NotificationRepositoryDouble()
    conversation_client = ConversationClientDouble()
    service = NotificationService(
        repository,
        DestinationServiceDouble(_destination()),
        conversation_client,
    )

    response = TestClient(_app(service)).post(
        "/api/notifications/send",
        json={
            "destination_id": DESTINATION_ID,
            "risk_id": RISK_ID,
            "title": "Attacker title",
            "body": "Attacker body",
            "risk": {"summary": "Attacker risk"},
            "conversation_reference": {"id": "attacker-route"},
            "service_url": "https://attacker.example",
        },
    )

    assert response.status_code == 200
    assert "Attacker" not in response.text
    assert "Database Risk Title" in json.dumps(conversation_client.calls[0][1])
    assert repository.created[0]["risk_id"] == RISK_ID


@pytest.mark.asyncio
async def test_provider_failure_marks_notification_failed_with_safe_error():
    repository = NotificationRepositoryDouble()
    service = NotificationService(
        repository,
        DestinationServiceDouble(_destination()),
        ConversationClientDouble(error=RuntimeError("Authorization Bearer secret-token")),
    )

    with pytest.raises(RuntimeError):
        await service.send(DESTINATION_ID, {"contentType": "adaptive"})

    assert repository.created[0]["status"] == "pending"
    assert len(repository.failed) == 1
    assert repository.failed[0][1] == "RuntimeError: outbound notification failed"
    assert "secret-token" not in repository.failed[0][1]


@pytest.mark.asyncio
async def test_resource_response_id_is_persisted_as_teams_message_id():
    repository = NotificationRepositoryDouble()
    service = NotificationService(
        repository,
        DestinationServiceDouble(_destination()),
        ConversationClientDouble(result=SimpleNamespace(id="resource-message-1")),
    )

    notification_id = await service.send(DESTINATION_ID, {"contentType": "adaptive"})

    assert repository.sent == [(notification_id, "resource-message-1")]


@pytest.mark.parametrize(
    ("destination", "status_code", "error_code"),
    [
        (None, 404, "DESTINATION_NOT_FOUND"),
        (_destination(active=False), 409, "DESTINATION_UNAVAILABLE"),
    ],
)
def test_unknown_or_inactive_destination_is_rejected(destination, status_code, error_code):
    service = NotificationService(
        NotificationRepositoryDouble(),
        DestinationServiceDouble(destination),
        ConversationClientDouble(),
    )

    response = TestClient(_app(service)).post(
        "/api/notifications/send",
        json={
            "destination_id": DESTINATION_ID,
            "risk_id": RISK_ID,
        },
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == error_code


def test_required_text_is_validated_and_trimmed():
    service = NotificationService(
        NotificationRepositoryDouble(),
        DestinationServiceDouble(_destination()),
        ConversationClientDouble(),
    )

    response = TestClient(_app(service)).post(
        "/api/notifications/send",
        json={"destination_id": "  ", "risk_id": RISK_ID},
    )
    assert response.status_code == 422
