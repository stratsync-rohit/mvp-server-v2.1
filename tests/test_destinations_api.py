"""Tests for trusted discovered-channel destination resolution."""

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.clients.teams_conversation_client import TeamsConversationClient
from src.exceptions import AppError
from src.schemas.destination import Destination
from src.services.destination_service import DestinationService


def _channel(channel_id: str = "channel-1", *, available: bool = True) -> dict:
    """Build a trusted discovered-channel fixture."""
    return {
        "_id": "must-not-leak",
        "tenant_id": "tenant-1",
        "team_id": "team-1",
        "channel_id": channel_id,
        "team_name": "Bot test",
        "channel_name": "test2",
        "conversation_id": "stale-installation-conversation",
        "service_url": "https://smba.example",
        "available": available,
        "access_token": "must-not-leak",
    }


class ChannelRepository:
    """In-memory discovered-channel repository double."""

    def __init__(self, documents=None):
        self.documents = documents or {}
        self.lookups = []

    async def get(self, tenant_id, team_id, channel_id):
        self.lookups.append((tenant_id, team_id, channel_id))
        return self.documents.get((tenant_id, team_id, channel_id))


class DestinationRepository:
    """In-memory destination repository double."""

    def __init__(self):
        self.saved = {}

    async def upsert(self, destination):
        self.saved[destination.destination_id] = destination

    async def get(self, destination_id):
        return self.saved.get(destination_id)


class ConversationClient:
    """Provider-boundary double that records the trusted route."""

    def __init__(self):
        self.references = []

    def build_channel_reference(self, **values):
        self.references.append(values)
        return {
            "channelId": "msteams",
            "serviceUrl": values["service_url"],
            "conversation": {"id": values["channel_id"], "tenantId": values["tenant_id"]},
        }

    async def resolve_conversation(self, reference):
        return reference


@pytest.mark.asyncio
async def test_valid_discovered_channel_resolves_channel_specific_destination():
    channel_repository = ChannelRepository({("tenant-1", "team-1", "channel-1"): _channel()})
    destination_repository = DestinationRepository()
    conversation_client = ConversationClient()
    service = DestinationService(
        destination_repository, conversation_client, channel_repository
    )

    destination = await service.resolve_discovered_channel("tenant-1", "team-1", "channel-1")

    assert destination.destination_id == "tenant-1:team-1:channel-1"
    assert destination.conversation_id == "channel-1"
    assert destination.conversation_id != "stale-installation-conversation"
    assert destination.team_name == "Bot test"
    assert destination.channel_name == "test2"
    assert conversation_client.references[0] == {
        "tenant_id": "tenant-1", "channel_id": "channel-1",
        "service_url": "https://smba.example",
    }


@pytest.mark.asyncio
async def test_repeated_resolution_is_idempotent_and_channels_are_distinct():
    channel_repository = ChannelRepository({
        ("tenant-1", "team-1", "channel-1"): _channel("channel-1"),
        ("tenant-1", "team-1", "channel-2"): _channel("channel-2"),
    })
    destination_repository = DestinationRepository()
    service = DestinationService(destination_repository, ConversationClient(), channel_repository)

    first = await service.resolve_discovered_channel("tenant-1", "team-1", "channel-1")
    repeated = await service.resolve_discovered_channel("tenant-1", "team-1", "channel-1")
    different = await service.resolve_discovered_channel("tenant-1", "team-1", "channel-2")

    assert first.destination_id == repeated.destination_id
    assert first.destination_id != different.destination_id
    assert len(destination_repository.saved) == 2


@pytest.mark.asyncio
async def test_unknown_and_unavailable_channels_are_rejected():
    destination_repository = DestinationRepository()
    service = DestinationService(
        destination_repository,
        ConversationClient(),
        ChannelRepository({("tenant-1", "team-1", "offline"): _channel("offline", available=False)}),
    )

    with pytest.raises(AppError) as missing:
        await service.resolve_discovered_channel("tenant-1", "team-1", "unknown")
    with pytest.raises(AppError) as unavailable:
        await service.resolve_discovered_channel("tenant-1", "team-1", "offline")

    assert missing.value.status_code == 404
    assert unavailable.value.status_code == 409


def test_route_accepts_only_identifiers_and_returns_safe_metadata():
    captured = {}

    class DestinationServiceDouble:
        async def resolve_discovered_channel(self, tenant_id, team_id, channel_id):
            captured.update({"tenant_id": tenant_id, "team_id": team_id, "channel_id": channel_id})
            return Destination(
                destination_id="tenant-1:team-1:channel-1",
                tenant_id=tenant_id,
                team_id=team_id,
                channel_id=channel_id,
                team_name="Bot test",
                channel_name="test2",
                conversation_id=channel_id,
                conversation_reference={"secret": "must-not-leak"},
            )

    app = create_app()
    app.state.container = Container(
        adapter=object(), bot=object(), destination_service=DestinationServiceDouble()
    )
    response = TestClient(app).post("/api/destinations/resolve", json={
        "tenant_id": "tenant-1", "team_id": "team-1", "channel_id": "channel-1",
        "service_url": "https://attacker.example",
        "conversation_reference": {"id": "attacker-route"},
    })

    assert response.status_code == 200
    assert captured == {"tenant_id": "tenant-1", "team_id": "team-1", "channel_id": "channel-1"}
    body = response.json()
    assert body["data"]["destination_id"] == "tenant-1:team-1:channel-1"
    assert body["data"]["team_name"] == "Bot test"
    assert "conversation_reference" not in body["data"]
    assert "secret" not in response.text
    assert "attacker" not in response.text


def test_sdk_client_builds_channel_specific_reference():
    client = TeamsConversationClient(object(), "bot-1")

    reference = client.build_channel_reference(
        tenant_id="tenant-1", channel_id="channel-1", service_url="https://smba.example"
    )

    assert reference["channelId"] == "msteams"
    assert reference["serviceUrl"] == "https://smba.example"
    assert reference["conversation"]["id"] == "channel-1"
    assert reference["conversation"]["tenantID"] == "tenant-1"
