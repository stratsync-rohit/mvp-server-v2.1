"""CloudAdapter boundary for outbound Teams conversation mechanics."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

try:
    from botbuilder.schema import (
        Activity,
        Attachment,
        ChannelAccount,
        ConversationAccount,
        ConversationReference,
    )
except ImportError:  # pragma: no cover
    Activity = Attachment = ChannelAccount = ConversationAccount = ConversationReference = None  # type: ignore[assignment,misc]

from src.exceptions import ProviderError


class TeamsConversationClient:
    """Keep provider-specific conversation continuation out of repositories."""

    def __init__(self, adapter: Any, bot_id: str | None = None) -> None:
        self.adapter = adapter
        self.bot_id = bot_id

    def build_channel_reference(self, *, tenant_id: str, channel_id: str,
                                service_url: str) -> dict[str, Any] | None:
        """Build a serialized SDK reference targeting one Teams channel."""
        if not tenant_id or not channel_id or not service_url or ConversationReference is None:
            return None
        reference = ConversationReference(
            channel_id="msteams",
            service_url=service_url,
            conversation=ConversationAccount(
                id=channel_id,
                tenant_id=tenant_id,
                conversation_type="channel",
                is_group=True,
            ),
            bot=ChannelAccount(id=self.bot_id) if self.bot_id else None,
        )
        return reference.serialize()

    async def resolve_conversation(self, reference: dict[str, Any]) -> dict[str, Any] | None:
        """Optionally pass route metadata through an adapter-specific resolver.

        The fallback is structural preparation only; it does not claim that
        Microsoft Teams has validated or created the conversation.
        """
        if not reference:
            return None
        resolver = getattr(self.adapter, "resolve_conversation", None)
        if resolver is None:
            return reference
        result = resolver(reference)
        return await result if hasattr(result, "__await__") else result

    async def send_activity(self, reference: dict[str, Any], activity: Any) -> Any:
        """Send an activity using the adapter's conversation continuation hook."""
        if isinstance(reference, dict) and ConversationReference is not None:
            reference = ConversationReference().deserialize(reference)
        activity = self._as_message_activity(activity)
        sender = getattr(self.adapter, "send_to_conversation", None)
        if sender is not None:
            result = sender(reference, activity)
            return await result if hasattr(result, "__await__") else result
        callback: Callable[[Any], Awaitable[Any]] | None = None
        continuer = getattr(self.adapter, "continue_conversation", None)
        if continuer is not None:
            response_holder: dict[str, Any] = {}

            async def callback(turn_context: Any) -> Any:
                response_holder["response"] = await turn_context.send_activity(activity)

            result = continuer(reference, callback, self.bot_id)
            if hasattr(result, "__await__"):
                await result
            return response_holder.get("response")
        raise ProviderError("CloudAdapter has no outbound conversation method")

    async def send_card_in_context(self, turn_context: Any, card: dict[str, Any]) -> Any:
        """Send one Adaptive Card through an already authenticated turn context."""
        activity = self._as_message_activity(card)
        result = turn_context.send_activity(activity)
        return await result if hasattr(result, "__await__") else result

    @staticmethod
    def _as_message_activity(activity: Any) -> Any:
        """Convert the internal card envelope to one Bot Framework message."""
        if isinstance(activity, dict) and activity.get("contentType") and Activity is not None:
            return Activity(type="message", attachments=[Attachment(
                content_type=activity["contentType"], content=activity.get("content", {})
            )])
        return activity
