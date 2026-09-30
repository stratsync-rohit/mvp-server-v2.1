"""Focused tests for outbound message-ID capture and reaction correlation."""

from types import SimpleNamespace

import pytest

from src.clients.teams_conversation_client import TeamsConversationClient
from src.repositories.reaction_repository import ReactionRepository
from src.services.reaction_service import ReactionService


@pytest.mark.asyncio
async def test_continue_conversation_captures_callback_response_once():
    response = SimpleNamespace(id="resource-message-1")

    class TurnContext:
        def __init__(self):
            self.calls = 0

        async def send_activity(self, activity):
            self.calls += 1
            return response

    class Adapter:
        def __init__(self):
            self.context = TurnContext()

        async def continue_conversation(self, reference, callback, bot_id):
            await callback(self.context)
            return None

    adapter = Adapter()
    client = TeamsConversationClient(adapter, "bot-1")

    result = await client.send_activity(
        {"channelId": "msteams", "conversation": {"id": "channel-1"}},
        {"contentType": "application/vnd.microsoft.card.adaptive", "content": {}},
    )

    assert result is response
    assert result.id == "resource-message-1"
    assert adapter.context.calls == 1


@pytest.mark.asyncio
async def test_send_card_in_context_formats_and_sends_one_new_activity():
    class TurnContext:
        def __init__(self):
            self.calls = []

        async def send_activity(self, activity):
            self.calls.append(activity)
            return SimpleNamespace(id="new-view-message")

    context = TurnContext()
    card = {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"type": "AdaptiveCard", "version": "1.4", "body": []},
    }
    result = await TeamsConversationClient(object()).send_card_in_context(context, card)

    assert result.id == "new-view-message"
    assert len(context.calls) == 1
    assert context.calls[0].type == "message"
    assert context.calls[0].attachments[0].content_type == card["contentType"]


class NotificationRepositoryDouble:
    """Notification lookup double keyed by the actual Teams message ID."""

    def __init__(self):
        self.lookups = []

    async def get_by_message_id(self, message_id, tenant_id=None):
        self.lookups.append((message_id, tenant_id))
        if message_id == "resource-message-1" and tenant_id == "tenant-1":
            return {
                "notification_id": "notification-1",
                "destination_id": "tenant-1:team-1:channel-1",
                "tenant_id": "tenant-1",
            }
        return None


def _reaction_activity(*, added=None, removed=None):
    """Build a serialized reaction activity for the service boundary."""
    return SimpleNamespace(serialize=lambda: {
        "id": "reaction-activity-1",
        "replyToId": "resource-message-1",
        "from": {"aadObjectId": "user-1"},
        "channelData": {"tenant": {"id": "tenant-1"}},
        "reactionsAdded": added or [],
        "reactionsRemoved": removed or [],
    })


@pytest.mark.asyncio
async def test_reaction_add_and_remove_correlate_by_stored_message_id():
    class ReactionCollection:
        def __init__(self):
            self.documents = {}

        async def update_one(self, query, update, upsert=False):
            key = tuple(sorted(query.items()))
            self.documents.setdefault(key, {}).update(update["$set"])

    collection = ReactionCollection()
    reaction_repository = ReactionRepository(collection=collection)
    notification_repository = NotificationRepositoryDouble()
    service = ReactionService(reaction_repository, notification_repository)

    await service.handle(SimpleNamespace(
        activity=_reaction_activity(added=[{"type": "like"}])
    ))
    await service.handle(SimpleNamespace(
        activity=_reaction_activity(removed=[{"type": "like"}])
    ))

    assert notification_repository.lookups == [
        ("resource-message-1", "tenant-1"),
        ("resource-message-1", "tenant-1"),
    ]
    assert len(collection.documents) == 1
    document = next(iter(collection.documents.values()))
    assert document["teams_message_id"] == "resource-message-1"
    assert document["notification_id"] == "notification-1"
    assert document["is_active"] is False
