"""Regression tests for authenticated Teams channel discovery."""

from types import SimpleNamespace

import pytest

from src.clients import teams_client
from src.clients.teams_client import TeamsClient
from src.bot.handlers.risk_bot import RiskBot
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.services.installation_service import InstallationService
from src.services.teams_service import TeamsService
from src.schemas.teams import TeamsContext


@pytest.mark.asyncio
async def test_teams_client_passes_explicit_team_id_to_sdk(monkeypatch):
    class TeamsInfoDouble:
        calls = []

        @staticmethod
        async def get_team_channels(turn_context, team_id):
            TeamsInfoDouble.calls.append((turn_context, team_id))
            return ["general", "test1"]

    monkeypatch.setattr(teams_client, "TeamsInfo", TeamsInfoDouble)
    turn_context = object()

    channels = await TeamsClient().get_team_channels(turn_context, "trusted-team-id")

    assert channels == ["general", "test1"]
    assert TeamsInfoDouble.calls == [(turn_context, "trusted-team-id")]


@pytest.mark.asyncio
async def test_installation_discovery_uses_authenticated_team_context():
    class InstallationRepository:
        def __init__(self):
            self.saved = []

        async def upsert(self, installation):
            self.saved.append(installation)

    class TeamsServiceDouble:
        def __init__(self):
            self.calls = []

        async def discover_channels(self, turn_context, context):
            self.calls.append((turn_context, context))

    turn_context = SimpleNamespace(activity={
        "serviceUrl": "https://teams.example",
        "conversation": {"id": "conversation-id"},
        "channelData": {
            "tenant": {"id": "tenant-id"},
            "team": {"id": "trusted-team-id", "name": "Risk Team"},
        },
    })
    installation_repository = InstallationRepository()
    teams_service = TeamsServiceDouble()

    await InstallationService(installation_repository, teams_service).add(turn_context)

    assert installation_repository.saved[0].team_id == "trusted-team-id"
    assert teams_service.calls[0][1].team_id == "trusted-team-id"
    assert teams_service.calls[0][1].conversation_id != teams_service.calls[0][1].team_id


@pytest.mark.asyncio
async def test_single_team_id_result_is_persisted_as_general_with_installation(caplog):
    class InstallationRepository:
        def __init__(self):
            self.saved = []

        async def upsert(self, installation):
            self.saved.append(installation)

    class ChannelRepository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    class Client:
        async def get_team_channels(self, turn_context, team_id):
            return [SimpleNamespace(id=team_id)]

    installation_repository = InstallationRepository()
    channel_repository = ChannelRepository()
    teams_service = TeamsService(Client(), channel_repository)
    turn_context = SimpleNamespace(activity={
        "type": "installationUpdate",
        "conversation": {"id": "installation-conversation"},
        "channelData": {
            "tenant": {"id": "tenant-id"},
            "team": {"id": "team-id", "name": "Risk Team"},
        },
    })

    with caplog.at_level("INFO"):
        await InstallationService(installation_repository, teams_service).add(turn_context)

    assert len(installation_repository.saved) == 1
    assert len(channel_repository.saved) == 1
    assert channel_repository.saved[0].channel_id == "team-id"
    assert channel_repository.saved[0].channel_name == "General"
    assert "teams_channel_discovery_ambiguous_general_skipped" not in caplog.messages


@pytest.mark.asyncio
async def test_discovery_logs_start_completion_and_persists_existing_channels(caplog):
    class Client:
        async def get_team_channels(self, turn_context, team_id):
            assert team_id == "team-id"
            return [
                SimpleNamespace(id="team-id", name="General"),
                SimpleNamespace(id="test1-id", name="test1"),
            ]

    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    context = TeamsContext(
        tenant_id="tenant-id", team_id="team-id", team_name="Risk Team"
    )

    with caplog.at_level("INFO"):
        discovered = await TeamsService(Client(), repository).discover_channels(
            object(), context
        )

    assert [(channel.channel_id, channel.channel_name) for channel in discovered] == [
        ("team-id", "General"),
        ("test1-id", "test1"),
    ]
    assert [channel.available for channel in repository.saved] == [True, True]
    assert "teams_channel_discovery_started" in caplog.messages
    assert "teams_channel_discovery_completed" in caplog.messages
    completed = next(
        record for record in caplog.records
        if record.message == "teams_channel_discovery_completed"
    )
    assert completed.channel_count == 2


def _channel_activity(channel_id, channel_name=None, activity_type="message"):
    channel = {"id": channel_id}
    if channel_name is not None:
        channel["name"] = channel_name
    return SimpleNamespace(activity={
        "type": activity_type,
        "serviceUrl": "https://teams.example",
        "conversation": {"id": "channel-conversation", "conversationType": "channel"},
        "channelData": {
            "tenant": {"id": "tenant-id"},
            "team": {"id": "team-id"},
            "channel": channel,
        },
    })


@pytest.mark.asyncio
async def test_real_message_registers_selected_channel_and_is_idempotent():
    class Collection:
        def __init__(self):
            self.documents = {}

        async def update_one(self, query, update, upsert=False):
            identity = tuple(query[field] for field in ("tenant_id", "team_id", "channel_id"))
            if identity not in self.documents and upsert:
                self.documents[identity] = {}
            self.documents[identity].update(update["$set"])
            self.documents[identity].update(update.get("$setOnInsert", {}))

    collection = Collection()
    repository = DiscoveredChannelRepository(collection=collection)
    service = TeamsService(object(), repository)
    turn_context = _channel_activity("test1-id", "test1")
    bot = RiskBot(teams_service=service)

    await bot.on_message_activity(turn_context)
    await bot.on_message_activity(turn_context)

    assert list(collection.documents) == [("tenant-id", "team-id", "test1-id")]
    assert collection.documents[("tenant-id", "team-id", "test1-id")]["channel_name"] == "test1"


@pytest.mark.asyncio
async def test_genuine_general_activity_uses_general_fallback():
    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    service = TeamsService(object(), repository)

    await service.register_channel_from_activity(
        _channel_activity("team-id", activity_type="message")
    )

    assert repository.saved[0].channel_name == "General"


@pytest.mark.asyncio
async def test_installation_update_never_uses_activity_registration_path():
    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    service = TeamsService(object(), repository)

    assert await service.register_channel_from_activity(
        _channel_activity("team-id", activity_type="installationUpdate")
    ) is None
    assert repository.saved == []
