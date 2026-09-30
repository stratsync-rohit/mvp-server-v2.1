"""Tests for persisted Details and Mitigation notification sends."""

from types import SimpleNamespace

import pytest

from src.services.notification_service import NotificationService
from src.services.reaction_service import ReactionService


class NotificationRepositoryDouble:
    """Persistence double recording notification lifecycle events."""

    def __init__(self):
        self.events = []
        self.created = []
        self.sent = []
        self.failed = []

    async def create(self, notification):
        self.events.append("pending")
        self.created.append(notification)

    async def mark_sent(self, notification_id, message_id):
        self.events.append("sent")
        self.sent.append((notification_id, message_id))

    async def mark_failed(self, notification_id, error):
        self.events.append("failed")
        self.failed.append((notification_id, error))


class ConversationClientDouble:
    """Authenticated-context provider double."""

    def __init__(self, result=None, error=None):
        self.result = result or {"id": "view-message-1"}
        self.error = error
        self.calls = []

    async def send_card_in_context(self, turn_context, card):
        self.calls.append((turn_context, card))
        if self.error:
            raise self.error
        return self.result

    def create_conversation(self, *args, **kwargs):
        raise AssertionError("create_conversation must not be used")


def _turn_context():
    return SimpleNamespace(activity={
        "channelData": {
            "tenant": {"id": "tenant-authenticated"},
            "team": {"id": "team-authenticated"},
            "channel": {"id": "channel-authenticated"},
        },
        "conversation": {"id": "conversation-not-identity"},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("view_type", ["details", "mitigation"])
async def test_view_send_persists_pending_then_real_message_id(view_type):
    repository = NotificationRepositoryDouble()
    conversation_client = ConversationClientDouble(
        result=SimpleNamespace(id=f"{view_type}-message-1")
    )
    service = NotificationService(repository, object(), conversation_client)
    card = {"contentType": "application/vnd.microsoft.card.adaptive", "content": {}}

    notification_id = await service.send_in_context(
        _turn_context(), card, risk_id="RSK-1", view_type=view_type
    )

    document = repository.created[0]
    assert document["notification_id"] == notification_id
    assert document["destination_id"] == (
        "tenant-authenticated:team-authenticated:channel-authenticated"
    )
    assert document["tenant_id"] == "tenant-authenticated"
    assert document["team_id"] == "team-authenticated"
    assert document["channel_id"] == "channel-authenticated"
    assert document["notification_type"] == "risk_view"
    assert document["view_type"] == view_type
    assert document["status"] == "pending"
    assert repository.events == ["pending", "sent"]
    assert repository.sent == [(notification_id, f"{view_type}-message-1")]
    assert len(conversation_client.calls) == 1


@pytest.mark.asyncio
async def test_view_send_provider_failure_marks_notification_failed_safely():
    repository = NotificationRepositoryDouble()
    service = NotificationService(
        repository,
        object(),
        ConversationClientDouble(error=RuntimeError("provider token must not persist")),
    )

    with pytest.raises(RuntimeError):
        await service.send_in_context(
            _turn_context(), {}, risk_id="RSK-1", view_type="details"
        )

    assert repository.events == ["pending", "failed"]
    assert repository.failed[0][1] == "RuntimeError: outbound notification failed"
    assert "token" not in repository.failed[0][1]


@pytest.mark.asyncio
async def test_reactions_correlate_details_and_mitigation_by_their_message_ids():
    class ReactionRepositoryDouble:
        def __init__(self):
            self.states = []

        async def set_state(self, state):
            self.states.append(state)

    class NotificationLookup:
        async def get_by_message_id(self, message_id, tenant_id=None):
            return {
                "details-message-1": {"notification_id": "details-notification", "destination_id": "d1"},
                "mitigation-message-1": {"notification_id": "mitigation-notification", "destination_id": "m1"},
            }.get(message_id)

    service = ReactionService(ReactionRepositoryDouble(), NotificationLookup())
    for message_id in ("details-message-1", "mitigation-message-1"):
        activity = SimpleNamespace(activity=SimpleNamespace(serialize=lambda message_id=message_id: {
            "replyToId": message_id,
            "from": {"aadObjectId": "user-1"},
            "channelData": {"tenant": {"id": "tenant-authenticated"}},
            "reactionsAdded": [{"type": "like"}],
            "reactionsRemoved": [],
        }))
        await service.handle(activity)

    states = service.repository.states
    assert [(state["notification_id"], state["teams_message_id"]) for state in states] == [
        ("details-notification", "details-message-1"),
        ("mitigation-notification", "mitigation-message-1"),
    ]
