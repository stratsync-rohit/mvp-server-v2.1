"""Tests for safe notification and reaction read APIs."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.services.notification_service import NotificationService


NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def _notification(notification_id: str, *, view_type: str | None = None, offset: int = 0) -> dict:
    return {
        "_id": f"mongo-{notification_id}",
        "notification_id": notification_id,
        "destination_id": "tenant:team:channel",
        "risk_id": "RSK-1",
        "tenant_id": "tenant",
        "team_id": "team",
        "channel_id": "channel",
        "notification_type": "risk_view" if view_type else None,
        "view_type": view_type,
        "status": "sent",
        "teams_message_id": f"message-{notification_id}",
        "created_at": NOW.replace(day=30 - offset),
        "updated_at": NOW,
        "card": {"secret": "must-not-leak"},
        "conversation_reference": {"token": "must-not-leak"},
        "service_url": "https://must-not-leak.example",
    }


class NotificationRepositoryDouble:
    def __init__(self, documents):
        self.documents = documents

    async def list(self, *, risk_id=None, destination_id=None, status=None,
                   notification_type=None, view_type=None, limit=50):
        documents = self.documents
        for field, value in {
            "risk_id": risk_id,
            "destination_id": destination_id,
            "status": status,
            "notification_type": notification_type,
            "view_type": view_type,
        }.items():
            if value is not None:
                documents = [document for document in documents if document.get(field) == value]
        return sorted(documents, key=lambda document: document["created_at"], reverse=True)[:limit]

    async def get_by_notification_id(self, notification_id):
        return next(
            (document for document in self.documents
             if document["notification_id"] == notification_id),
            None,
        )


class ReactionRepositoryDouble:
    def __init__(self, records):
        self.records = records
        self.batch_ids = []

    async def list_active_for_notification_ids(self, notification_ids):
        self.batch_ids.append(notification_ids)
        return [record for record in self.records
                if record["notification_id"] in notification_ids and record["is_active"]]

    async def list_by_notification_id(self, notification_id, *, include_inactive=False):
        return [record for record in self.records
                if record["notification_id"] == notification_id
                and (include_inactive or record["is_active"])]


def _client(documents, records):
    app = create_app()
    app.state.container = Container(
        adapter=object(),
        bot=object(),
        notification_service=NotificationService(
            NotificationRepositoryDouble(documents),
            object(),
            object(),
            ReactionRepositoryDouble(records),
        ),
    )
    return TestClient(app)


def test_notification_list_is_safe_newest_first_filtered_and_batched():
    documents = [
        _notification("old", offset=2),
        _notification("details", view_type="details", offset=1),
        _notification("new", view_type="mitigation"),
    ]
    records = [
        {"notification_id": "new", "reaction": "laugh", "user_aad_id": "u1",
         "is_active": True, "teams_message_id": "message-new"},
        {"notification_id": "new", "reaction": "laugh", "user_aad_id": "u2",
         "is_active": False, "teams_message_id": "message-new"},
        {"notification_id": "new", "reaction": "surprised", "user_aad_id": "u3",
         "is_active": True, "teams_message_id": "message-new"},
    ]

    response = _client(documents, records).get(
        "/api/notifications?view_type=mitigation&limit=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["notification_id"] for item in body["data"]] == ["new"]
    assert body["data"][0]["reaction_summary"] == {
        "total": 2,
        "counts": {"laugh": 1, "surprised": 1},
    }
    assert "mongo-new" not in response.text
    assert "must-not-leak" not in response.text


def test_notification_detail_supports_legacy_records_and_returns_404():
    client = _client([_notification("legacy")], [])

    detail = client.get("/api/notifications/legacy")
    missing = client.get("/api/notifications/unknown")

    assert detail.status_code == 200
    assert detail.json()["data"]["view_type"] is None
    assert detail.json()["data"]["reaction_summary"] == {"total": 0, "counts": {}}
    assert missing.status_code == 404


def test_reactions_default_to_active_and_can_include_inactive():
    documents = [_notification("one", view_type="details")]
    records = [
        {"notification_id": "one", "reaction": "heart", "user_aad_id": "u1",
         "is_active": True, "teams_message_id": "message-one"},
        {"notification_id": "one", "reaction": "heart", "user_aad_id": "u1",
         "is_active": False, "teams_message_id": "message-one"},
    ]
    client = _client(documents, records)

    active = client.get("/api/notifications/one/reactions")
    all_states = client.get("/api/notifications/one/reactions?include_inactive=true")

    assert len(active.json()["data"]["reactions"]) == 1
    assert len(all_states.json()["data"]["reactions"]) == 2
    assert all_states.json()["data"]["summary"] == {
        "total": 1,
        "counts": {"heart": 1},
    }
