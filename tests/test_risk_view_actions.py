"""Tests for dynamic risk-view actions and server-side view rendering."""

import json
from types import SimpleNamespace

import pytest

from src.bot.handlers.risk_bot import RiskBot
from src.exceptions import AppError
from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
from src.services.risk_view_service import RiskViewService


def _risk():
    return {
        "_id": "must-not-leak",
        "risk_id": "RSK-1",
        "title": "Inventory action required",
        "views": {
            "notification": {
                "blocks": [{
                    "type": "metrics",
                    "columns": [
                        {"key": "label", "label": "Metric"},
                        {"key": "value", "label": "Value"},
                        {"key": "status", "label": "Status"},
                    ],
                    "items": [{"label": "Floor Price", "value": "S$60/unit", "status": "good"}],
                }],
            },
            "details": {
                "action_label": "Customer Targets",
                "title": "Customer Targets",
                "subtitle": "Recent customer purchases and unconverted enquiries",
                "blocks": [{
                    "type": "table",
                    "columns": [
                        {"key": "customer_segment", "label": "Segment"},
                        {"key": "quoted_price", "label": "Quoted Price"},
                    ],
                    "rows": [{"customer_segment": "Enterprise", "quoted_price": "S$72/unit"}],
                }],
            },
            "mitigation": {
                "action_label": "Mitigation Plan",
                "title": "Mitigation Plan",
                "subtitle": "Recommended commercial and inventory actions",
                "blocks": [{
                    "type": "action_list",
                    "items": [
                        {"order": 1, "title": "Review demand"},
                        {"order": 2, "title": "Contact supplier"},
                        {"order": 3, "title": "Update forecast"},
                    ],
                }],
            },
        },
    }


def test_notification_actions_are_dynamic_and_identifier_only():
    card = TeamsRiskCardRenderer().render_notification(_risk())
    actions = card["content"]["actions"]

    assert [action["title"] for action in actions] == ["Customer Targets", "Mitigation Plan"]
    assert all(action["type"] == "Action.Execute" for action in actions)
    assert [action["data"] for action in actions] == [
        {"action": "show_risk_view", "risk_id": "RSK-1", "view": "details"},
        {"action": "show_risk_view", "risk_id": "RSK-1", "view": "mitigation"},
    ]
    assert all(set(action["data"]) == {"action", "risk_id", "view"} for action in actions)
    assert "must-not-leak" not in json.dumps(actions)


def test_missing_view_omits_only_that_button_and_metric_status_is_not_visible():
    risk = _risk()
    risk["views"].pop("mitigation")
    card = TeamsRiskCardRenderer().render_notification(risk)
    serialized = json.dumps(card)

    assert [action["data"]["view"] for action in card["content"]["actions"]] == ["details"]
    assert "good" not in serialized
    assert "Floor Price" in serialized
    assert "S$60/unit" in serialized


class RiskServiceDouble:
    """Risk service double exposing the latest document per lookup."""

    def __init__(self, risk=None, error=None):
        self.risk = risk
        self.error = error
        self.lookups = []

    async def get(self, risk_id):
        self.lookups.append(risk_id)
        if self.error:
            raise self.error
        return self.risk


@pytest.mark.asyncio
async def test_risk_view_service_reloads_latest_details_and_mitigation_views():
    risk = _risk()
    risk_service = RiskServiceDouble(risk)
    service = RiskViewService(risk_service, TeamsRiskCardRenderer())

    details = await service.render("RSK-1", "details")
    mitigation = await service.render("RSK-1", "mitigation")

    assert risk_service.lookups == ["RSK-1", "RSK-1"]
    assert "Customer Targets" in json.dumps(details)
    assert "Enterprise" in json.dumps(details)
    assert "S$72/unit" in json.dumps(details)
    assert all(title in json.dumps(mitigation) for title in (
        "1. Review demand", "2. Contact supplier", "3. Update forecast"
    ))
    assert "must-not-leak" not in json.dumps(details)


@pytest.mark.asyncio
async def test_risk_view_service_rejects_invalid_or_missing_views():
    risk_service = RiskServiceDouble(_risk())
    service = RiskViewService(risk_service, TeamsRiskCardRenderer())

    with pytest.raises(AppError) as invalid:
        await service.render("RSK-1", "../../metadata")
    assert invalid.value.status_code == 400
    assert risk_service.lookups == []

    risk_service = RiskServiceDouble(error=AppError("RISK_NOT_FOUND", "missing", 404))
    service = RiskViewService(risk_service, TeamsRiskCardRenderer())
    with pytest.raises(AppError) as missing:
        await service.render("RSK-unknown", "details")
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_risk_bot_handles_adaptive_card_action_through_invoke_response():
    class RiskViewServiceDouble:
        def __init__(self):
            self.calls = []

        async def render(self, risk_id, view):
            self.calls.append((risk_id, view))
            return {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {"type": "AdaptiveCard", "version": "1.4", "body": []},
            }

    class NotificationServiceDouble:
        def __init__(self):
            self.calls = []

        async def send_in_context(self, turn_context, card, *, risk_id, view_type):
            self.calls.append((turn_context, card, risk_id, view_type))

    view_service = RiskViewServiceDouble()
    notification_service = NotificationServiceDouble()
    turn_context = SimpleNamespace()
    bot = RiskBot(
        risk_view_service=view_service,
        notification_service=notification_service,
    )
    response = await bot.on_adaptive_card_invoke(turn_context, SimpleNamespace(
        action={
            "type": "Action.Execute",
            "verb": "show_risk_view",
            "data": {"action": "show_risk_view", "risk_id": "RSK-1", "view": "details"},
        }
    ))

    assert response.status_code == 200
    assert response.type == "application/vnd.microsoft.activity.message"
    assert response.value == {"text": ""}
    assert view_service.calls == [("RSK-1", "details")]
    assert notification_service.calls == [(turn_context, {
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"type": "AdaptiveCard", "version": "1.4", "body": []},
    }, "RSK-1", "details")]


@pytest.mark.asyncio
async def test_details_and_mitigation_actions_each_send_one_new_card():
    class RiskViewServiceDouble:
        async def render(self, risk_id, view):
            return {"contentType": "application/vnd.microsoft.card.adaptive", "content": {
                "type": "AdaptiveCard", "view": view,
            }}

    class NotificationServiceDouble:
        def __init__(self):
            self.cards = []

        async def send_in_context(self, turn_context, card, *, risk_id, view_type):
            self.cards.append((card, risk_id, view_type))

    notification_service = NotificationServiceDouble()
    bot = RiskBot(
        risk_view_service=RiskViewServiceDouble(),
        notification_service=notification_service,
    )
    for view in ("details", "mitigation"):
        response = await bot.on_adaptive_card_invoke(SimpleNamespace(), SimpleNamespace(
            action={
                "type": "Action.Execute",
                "verb": "show_risk_view",
                "data": {"action": "show_risk_view", "risk_id": "RSK-1", "view": view},
            }
        ))
        assert response.type == "application/vnd.microsoft.activity.message"

    assert [card[0]["content"]["view"] for card in notification_service.cards] == ["details", "mitigation"]
    assert [card[2] for card in notification_service.cards] == ["details", "mitigation"]
    assert len(notification_service.cards) == 2


@pytest.mark.asyncio
async def test_risk_bot_rejects_invalid_view_action_without_loading_data():
    class RiskViewServiceDouble:
        async def render(self, risk_id, view):
            raise AssertionError("invalid view must be rejected before service delegation")

    bot = RiskBot(risk_view_service=RiskViewServiceDouble())
    response = await bot.on_adaptive_card_invoke(SimpleNamespace(), SimpleNamespace(
        action={
            "type": "Action.Execute",
            "verb": "show_risk_view",
            "data": {"action": "show_risk_view", "risk_id": "RSK-1", "view": "../secrets"},
        }
    ))

    assert response.status_code == 400
    assert response.type == "application/vnd.microsoft.error"
