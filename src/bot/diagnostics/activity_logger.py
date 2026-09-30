"""Structured, secret-safe diagnostics for Bot Framework activities."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "token",
    "password",
    "client_secret",
    "clientsecret",
    "accesstoken",
    "apikey",
    "api_key",
    "bearertoken",
    "secret",
}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Convert an SDK model or mapping into a shallow mapping safely."""
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "serialize"):
        serialized = value.serialize()
        if isinstance(serialized, Mapping):
            return serialized
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def sanitize_activity(value: Any) -> dict[str, Any]:
    """Return a recursively sanitized activity representation for debug logs."""
    def sanitize(item: Any, key: str = "") -> Any:
        if key.lower().replace("-", "_") in _SENSITIVE_KEYS:
            return "[REDACTED]"
        if isinstance(item, Mapping):
            return {str(k): sanitize(v, str(k)) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [sanitize(v) for v in item]
        if hasattr(item, "serialize"):
            return sanitize(item.serialize())
        if hasattr(item, "__dict__") and not isinstance(item, type):
            return sanitize(_as_mapping(item))
        return item

    return sanitize(_as_mapping(value))


def _nested(value: Mapping[str, Any], *keys: str) -> Any:
    """Read a nested field from either a raw activity or serialized SDK data."""
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def activity_metadata(activity: Any) -> dict[str, Any]:
    """Extract useful non-secret fields from an activity for operational logs."""
    data = _as_mapping(activity)
    channel_data = data.get("channelData") or data.get("channel_data") or {}
    conversation = data.get("conversation") or {}
    recipient = data.get("recipient") or {}
    sender = data.get("from") or data.get("from_property") or {}
    tenant = channel_data.get("tenant") or {}
    team = channel_data.get("team") or {}
    channel = channel_data.get("channel") or {}
    return {
        "activity_type": data.get("type"),
        "activity_id": data.get("id"),
        "timestamp": data.get("timestamp"),
        "service_url": data.get("serviceUrl") or data.get("service_url"),
        "conversation_id": conversation.get("id"),
        "conversation_type": conversation.get("conversationType")
        or conversation.get("conversation_type"),
        "conversation_tenant_id": conversation.get("tenantId")
        or conversation.get("tenant_id"),
        "recipient_id": recipient.get("id"),
        "from_id": sender.get("id"),
        "tenant_id": tenant.get("id"),
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "channel_id": channel.get("id"),
        "channel_name": channel.get("name"),
        "event_type": channel_data.get("eventType")
        or channel_data.get("event_type"),
        "action": data.get("action"),
        "members_added": data.get("membersAdded") or data.get("members_added"),
        "members_removed": data.get("membersRemoved")
        or data.get("members_removed"),
    }


def log_activity(activity: Any, *, debug: bool = False) -> dict[str, Any]:
    """Log safe activity metadata and optionally its sanitized raw payload."""
    metadata = activity_metadata(activity)
    logger.info("teams_activity_received", extra=metadata)
    if debug:
        logger.debug("teams_activity_raw", extra={"activity": sanitize_activity(activity)})
    return metadata
