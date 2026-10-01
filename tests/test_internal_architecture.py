"""Focused unit coverage for the internal Teams architecture."""

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.bot.diagnostics.activity_logger import activity_metadata, sanitize_activity
from src.bot.handlers.risk_bot import RiskBot
from src.repositories.discovered_channel_repository import DiscoveredChannelRepository
from src.repositories.destination_repository import DestinationRepository
from src.repositories.notification_repository import NotificationRepository
from src.repositories.processed_activity_repository import ProcessedActivityRepository
from src.repositories.team_installation_repository import TeamInstallationRepository
from src.repositories.reaction_repository import ReactionRepository
from src.schemas.destination import Destination
from src.schemas.destination import build_destination_id
from src.schemas.teams import TeamInstallation, TeamsContext
from src.services.destination_service import DestinationService
from src.services.installation_service import InstallationService
from src.services.notification_service import NotificationService
from src.services.reaction_service import ReactionService
from src.services.teams_service import TeamsService


class MemoryCollection:
    """Minimal async collection double for repository contract tests."""

    def __init__(self) -> None:
        self.documents = {}

    async def update_one(self, query, update, upsert=False):
        key = tuple(sorted((name, query[name]) for name in query if name != "$or"))
        document = self.documents.setdefault(key, {}) if upsert else self.documents.get(key, {})
        document.update(update.get("$set", {}))
        document.update(update.get("$setOnInsert", {}))

    async def find_one(self, query):
        for document in self.documents.values():
            if all(document.get(k) == v for k, v in query.items()):
                return document
        return None


def test_activity_diagnostics_redact_secrets_and_extract_safe_context():
    payload = {"type": "message", "id": "a1", "token": "secret", "channelData": {
        "tenant": {"id": "tenant-1"}, "team": {"id": "team-1", "name": "Risk"},
    }}

    assert sanitize_activity(payload)["token"] == "[REDACTED]"
    assert activity_metadata(payload)["tenant_id"] == "tenant-1"
    assert "authorization" not in activity_metadata(payload)


@pytest.mark.asyncio
async def test_installation_and_channel_repositories_use_logical_identity():
    installations = MemoryCollection()
    channels = MemoryCollection()
    installation_repo = TeamInstallationRepository(collection=installations)
    channel_repo = DiscoveredChannelRepository(collection=channels)

    await installation_repo.upsert(TeamInstallation(tenant_id="t", team_id="team"))
    await installation_repo.mark_inactive("t", "team")
    await channel_repo.upsert({"tenant_id": "t", "team_id": "team", "channel_id": "channel"})

    assert (await installation_repo.get("t", "team"))["is_active"] is False
    assert (await channel_repo.get("t", "team", "channel"))["channel_id"] == "channel"


@pytest.mark.asyncio
async def test_installation_upsert_preserves_installed_at_and_avoids_set_conflict(monkeypatch):
    class InstallationCollection:
        def __init__(self):
            self.document = None
            self.updates = []

        async def update_one(self, query, update, upsert=False):
            self.updates.append(deepcopy(update))
            if self.document is None and upsert:
                self.document = deepcopy(update["$setOnInsert"])
            self.document.update(deepcopy(update["$set"]))

        async def find_one(self, query):
            return self.document

    first_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second_time = datetime(2026, 1, 2, tzinfo=timezone.utc)
    times = iter((first_time, second_time))
    monkeypatch.setattr(
        "src.repositories.team_installation_repository.utcnow", lambda: next(times)
    )
    collection = InstallationCollection()
    repository = TeamInstallationRepository(collection=collection)

    await repository.upsert({"tenant_id": "tenant", "team_id": "team", "team_name": "Risk"})
    original_installed_at = collection.document["installed_at"]
    await repository.upsert({"tenant_id": "tenant", "team_id": "team", "team_name": "Risk renamed"})

    first_update, second_update = collection.updates
    assert original_installed_at == first_time
    assert collection.document["installed_at"] == first_time
    assert collection.document["updated_at"] == second_time
    assert collection.document["is_active"] is True
    assert collection.document["uninstalled_at"] is None
    assert "installed_at" not in first_update["$set"]
    assert "installed_at" not in second_update["$set"]
    assert first_update["$setOnInsert"]["installed_at"] == first_time


@pytest.mark.asyncio
async def test_destination_upsert_puts_created_at_only_in_set_on_insert(monkeypatch):
    class DestinationCollection:
        def __init__(self):
            self.document = None
            self.updates = []

        async def update_one(self, query, update, upsert=False):
            self.updates.append(deepcopy(update))
            if self.document is None and upsert:
                self.document = deepcopy(update["$setOnInsert"])
            self.document.update(deepcopy(update["$set"]))

    first_time = datetime(2026, 1, 3, tzinfo=timezone.utc)
    second_time = datetime(2026, 1, 4, tzinfo=timezone.utc)
    times = iter((first_time, second_time, second_time, second_time))
    monkeypatch.setattr("src.repositories.destination_repository.utcnow", lambda: next(times))
    collection = DestinationCollection()
    repository = DestinationRepository(collection=collection)

    destination = Destination(
        destination_id="tenant:team:channel",
        tenant_id="tenant",
        team_id="team",
        channel_id="channel",
    )
    await repository.upsert(destination)
    await repository.upsert(destination)

    first_update, second_update = collection.updates
    assert collection.document["created_at"] == first_time
    assert "created_at" not in first_update["$set"]
    assert "created_at" not in second_update["$set"]
    assert first_update["$setOnInsert"]["created_at"] == first_time
    assert second_update["$setOnInsert"]["created_at"] == second_time


@pytest.mark.asyncio
async def test_channel_discovery_persists_all_channels():
    class Client:
        async def get_team_channels(self, turn_context, team_id):
            return [{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}]

    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    service = TeamsService(Client(), repository)
    context = TeamsContext(tenant_id="tenant", team_id="team", team_name="Team")
    result = await service.discover_channels(SimpleNamespace(), context)

    assert [channel.channel_id for channel in result] == ["one", "two"]
    assert [channel.channel_id for channel in repository.saved] == ["one", "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (SimpleNamespace(id="channel", name="Normal"), "Normal"),
        (SimpleNamespace(id="channel", display_name="Display name"), "Display name"),
        ({"id": "channel", "displayName": "DisplayName"}, "DisplayName"),
        (SimpleNamespace(id="team"), None),
        (SimpleNamespace(id="other-channel"), None),
    ],
)
async def test_channel_discovery_resolves_name_variants_without_id_name_fallback(channel, expected):
    class Client:
        async def get_team_channels(self, turn_context, team_id):
            return [channel, SimpleNamespace(id="other-channel", name="Other")]

    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    service = TeamsService(Client(), repository)
    context = TeamsContext(tenant_id="tenant", team_id="team")

    result = await service.discover_channels(SimpleNamespace(), context)

    assert result[0].channel_name == expected


@pytest.mark.asyncio
async def test_default_channel_discovery_persists_general_idempotently():
    class Client:
        async def get_team_channels(self, turn_context, team_id):
            return [{"id": team_id}]

    collection = MemoryCollection()
    repository = DiscoveredChannelRepository(collection=collection)
    service = TeamsService(Client(), repository)
    context = TeamsContext(tenant_id="tenant", team_id="team")

    first = await service.discover_channels(SimpleNamespace(), context)
    second = await service.discover_channels(SimpleNamespace(), context)

    assert first[0].channel_id == second[0].channel_id == "team"
    assert first[0].channel_name is None
    assert second[0].channel_name is None
    assert await repository.get("tenant", "team", "team") is not None
    assert len(collection.documents) == 1


@pytest.mark.asyncio
async def test_conversation_update_delegates_to_teams_service():
    class TeamsServiceDouble:
        def __init__(self):
            self.activities = []

        async def handle_conversation_update(self, turn_context):
            self.activities.append(turn_context)

    service = TeamsServiceDouble()
    context = SimpleNamespace(activity={"type": "conversationUpdate"})
    await RiskBot(teams_service=service).on_conversation_update_activity(context)

    assert service.activities == [context]


@pytest.mark.asyncio
async def test_team_deleted_marks_authenticated_installation_inactive(caplog):
    class InstallationRepository:
        def __init__(self):
            self.calls = []

        async def mark_inactive(self, tenant_id, team_id):
            self.calls.append((tenant_id, team_id))

    class ChannelRepository:
        async def upsert(self, channel):
            raise AssertionError("teamDeleted must not persist a channel")

    activity = SimpleNamespace(activity={
        "type": "conversationUpdate",
        "channelData": {
            "eventType": "teamDeleted",
            "tenant": {"id": "tenant-authenticated"},
            "team": {"id": "team-deleted", "name": "Deleted Team"},
        },
    })
    installation_repository = InstallationRepository()
    service = TeamsService(object(), ChannelRepository(), installation_repository)

    with caplog.at_level("INFO"):
        assert await service.handle_conversation_update(activity) is None

    assert installation_repository.calls == [("tenant-authenticated", "team-deleted")]
    record = next(record for record in caplog.records if record.message == "teams_team_deleted")
    assert (record.tenant_id, record.team_id, record.team_name) == (
        "tenant-authenticated", "team-deleted", "Deleted Team"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel_data",
    [
        {"eventType": "teamDeleted", "team": {"id": "team-only"}},
        {"eventType": "teamDeleted", "tenant": {"id": "tenant-only"}},
    ],
)
async def test_team_deleted_skips_missing_identity(channel_data):
    class InstallationRepository:
        def __init__(self):
            self.calls = []

        async def mark_inactive(self, tenant_id, team_id):
            self.calls.append((tenant_id, team_id))

    activity = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": channel_data,
    })
    installation_repository = InstallationRepository()
    service = TeamsService(object(), object(), installation_repository)

    assert await service.handle_conversation_update(activity) is None
    assert installation_repository.calls == []


@pytest.mark.asyncio
async def test_installation_remove_marks_team_inactive():
    class InstallationRepository:
        def __init__(self):
            self.calls = []

        async def mark_inactive(self, tenant_id, team_id):
            self.calls.append((tenant_id, team_id))

    installation_repository = InstallationRepository()
    service = InstallationService(installation_repository, object())
    activity = SimpleNamespace(activity={
        "type": "installationUpdate",
        "channelData": {
            "tenant": {"id": "tenant"}, "team": {"id": "team"},
        },
    })

    await service.remove(activity)

    assert installation_repository.calls == [("tenant", "team")]


@pytest.mark.asyncio
async def test_channel_created_uses_team_name_from_activity():
    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    activity = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": {
            "eventType": "channelCreated", "tenant": {"id": "tenant"},
            "team": {"id": "team", "name": "Activity Team"},
            "channel": {"id": "channel", "name": "General"},
        },
    })
    repository = Repository()
    service = TeamsService(object(), repository)

    await service.handle_conversation_update(activity)

    assert repository.saved[0].team_name == "Activity Team"


@pytest.mark.asyncio
async def test_channel_created_resolves_team_name_from_installation():
    class ChannelRepository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    class InstallationRepository:
        async def get(self, tenant_id, team_id):
            assert (tenant_id, team_id) == ("tenant", "team")
            return {"team_name": "Installed Team"}

    activity = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": {
            "eventType": "channelCreated", "tenant": {"id": "tenant"},
            "team": {"id": "team"}, "channel": {"id": "channel"},
        },
    })
    repository = ChannelRepository()
    service = TeamsService(object(), repository, InstallationRepository())

    await service.handle_conversation_update(activity)

    assert repository.saved[0].team_name == "Installed Team"


@pytest.mark.asyncio
async def test_missing_installation_does_not_block_channel_persistence():
    class ChannelRepository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    class InstallationRepository:
        async def get(self, tenant_id, team_id):
            return None

    activity = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": {
            "eventType": "channelCreated", "tenant": {"id": "tenant"},
            "team": {"id": "team"}, "channel": {"id": "channel"},
        },
    })
    repository = ChannelRepository()
    service = TeamsService(object(), repository, InstallationRepository())

    await service.handle_conversation_update(activity)

    assert len(repository.saved) == 1
    assert repository.saved[0].team_name is None


@pytest.mark.asyncio
async def test_discovered_channel_does_not_overwrite_team_name_with_null():
    collection = MemoryCollection()
    repository = DiscoveredChannelRepository(collection=collection)
    identity = {"tenant_id": "tenant", "team_id": "team", "channel_id": "channel"}

    await repository.upsert({**identity, "team_name": "Existing Team", "channel_name": "General"})
    await repository.upsert({**identity, "team_name": None, "channel_name": "Renamed"})

    document = await repository.get("tenant", "team", "channel")
    assert document["team_name"] == "Existing Team"
    assert document["channel_name"] == "Renamed"


@pytest.mark.asyncio
async def test_channel_created_is_persisted_idempotently_with_channel_identity():
    class ChannelCollection:
        def __init__(self):
            self.documents = {}
            self.updates = []

        async def update_one(self, query, update, upsert=False):
            self.updates.append(deepcopy(update))
            identity = tuple(query[field] for field in ("tenant_id", "team_id", "channel_id"))
            if identity not in self.documents and upsert:
                self.documents[identity] = deepcopy(update["$setOnInsert"])
            self.documents[identity].update(deepcopy(update["$set"]))

        async def find_one(self, query):
            identity = tuple(query[field] for field in ("tenant_id", "team_id", "channel_id"))
            return self.documents.get(identity)

    class Client:
        async def get_team_channels(self, turn_context, team_id):
            return []

    def event(channel_name):
        return SimpleNamespace(activity={
            "type": "conversationUpdate",
            "serviceUrl": "https://teams.example",
            "conversation": {"id": "team-conversation-id"},
            "channelData": {
                "eventType": "channelCreated",
                "tenant": {"id": "tenant-1"},
                "team": {"id": "team-1", "name": "Risk"},
                "channel": {"id": "test2", "name": channel_name},
            },
        })

    collection = ChannelCollection()
    repository = DiscoveredChannelRepository(collection=collection)
    service = TeamsService(Client(), repository)
    first = await service.handle_conversation_update(event("test1"))
    original_discovered_at = collection.documents[("tenant-1", "team-1", "test2")]["discovered_at"]
    second = await service.handle_conversation_update(event("renamed"))

    document = await repository.get("tenant-1", "team-1", "test2")
    assert first.channel_id == second.channel_id == "test2"
    assert document["channel_id"] != document["conversation_id"]
    assert document["channel_name"] == "renamed"
    assert document["available"] is True
    assert document["discovered_at"] == original_discovered_at
    assert len(collection.documents) == 1
    assert all("discovered_at" not in update["$set"] for update in collection.updates)


@pytest.mark.asyncio
async def test_channel_created_skips_incomplete_and_non_channel_events():
    class Repository:
        def __init__(self):
            self.saved = []

        async def upsert(self, channel):
            self.saved.append(channel)

    repository = Repository()
    service = TeamsService(object(), repository)
    incomplete = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": {
            "eventType": "channelCreated", "team": {"id": "team"},
        },
    })
    other_event = SimpleNamespace(activity={
        "type": "conversationUpdate", "channelData": {
            "eventType": "channelDeleted", "tenant": {"id": "tenant"},
            "team": {"id": "team"}, "channel": {"id": "channel"},
        },
    })

    assert await service.handle_conversation_update(incomplete) is None
    assert await service.handle_conversation_update(other_event) is None
    assert repository.saved == []


def test_destination_identity_is_tenant_isolated():
    assert build_destination_id("t1", "team", "channel") != build_destination_id("t2", "team", "channel")


@pytest.mark.asyncio
async def test_destination_service_requires_provider_route_before_persisting():
    class ConversationClient:
        async def resolve_conversation(self, reference):
            return reference if reference.get("serviceUrl") else None

    class Repository:
        def __init__(self):
            self.saved = None

        async def upsert(self, destination):
            self.saved = destination

        async def get(self, destination_id):
            return None

    repository = Repository()
    service = DestinationService(repository, ConversationClient())
    assert await service.resolve({"tenant_id": "t", "team_id": "team", "channel_id": "c"}) is None
    destination = await service.resolve({"tenant_id": "t", "team_id": "team", "channel_id": "c",
                                         "service_url": "https://teams.example"})
    assert destination is not None
    assert destination.destination_id == "t:team:c"
    assert repository.saved is destination


@pytest.mark.asyncio
async def test_notification_send_persists_pending_then_sent_state():
    destination = Destination(
        destination_id="t:team:c", tenant_id="t", team_id="team", channel_id="c",
        conversation_reference={"conversation": {"id": "conversation"}},
    )

    class DestinationServiceDouble:
        async def get(self, destination_id):
            return destination

    class NotificationRepositoryDouble:
        def __init__(self):
            self.created = None
            self.sent = None

        async def create(self, notification):
            self.created = notification

        async def mark_sent(self, notification_id, message_id):
            self.sent = (notification_id, message_id)

        async def mark_failed(self, notification_id, error):
            raise AssertionError(error)

    class ConversationClientDouble:
        async def send_activity(self, reference, card):
            return {"id": "teams-message-1"}

    repository = NotificationRepositoryDouble()
    service = NotificationService(repository, DestinationServiceDouble(), ConversationClientDouble())
    notification_id = await service.send("t:team:c", {"contentType": "adaptive"})

    assert repository.created["status"] == "pending"
    assert repository.sent == (notification_id, "teams-message-1")


@pytest.mark.asyncio
async def test_reaction_service_persists_add_and_remove():
    class NotificationRepositoryDouble:
        async def get_by_message_id(self, message_id, tenant_id=None):
            return {"notification_id": "n1", "destination_id": "d1"}

    class ReactionRepositoryDouble:
        def __init__(self):
            self.states = []

        async def set_state(self, reaction):
            self.states.append(reaction)

    activity = {"replyToId": "teams-message-1", "from": {"aadObjectId": "user"},
                "channelData": {"tenant": {"id": "tenant"}},
                "reactionsAdded": [{"type": "like"}], "reactionsRemoved": [{"type": "heart"}]}
    reactions = ReactionRepositoryDouble()
    service = ReactionService(reactions, NotificationRepositoryDouble())
    await service.handle(SimpleNamespace(activity=SimpleNamespace(serialize=lambda: activity)))

    assert [state["is_active"] for state in reactions.states] == [True, False]
    assert all(state["tenant_id"] == "tenant" for state in reactions.states)


@pytest.mark.asyncio
async def test_processed_activity_claim_is_retry_safe():
    collection = MemoryCollection()
    repository = ProcessedActivityRepository(collection=collection)

    assert await repository.claim("activity-1", "message") is True
    assert await repository.claim("activity-1", "message") is False
    await repository.mark_completed("activity-1")
    assert await repository.claim("activity-1", "message") is False
