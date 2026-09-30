"""Tests for database-driven risk notification rendering."""

import json

import pytest

from src.exceptions import AppError
from src.renderers.teams_risk_card_renderer import TeamsRiskCardRenderer
from src.repositories.risk_repository import RiskRepository
from src.services.risk_service import RiskService


def _texts(value):
    """Return Adaptive Card text values in document order."""
    if isinstance(value, dict):
        result = []
        if isinstance(value.get("text"), str):
            result.append(value["text"])
        for fact in value.get("facts", []):
            if isinstance(fact, dict):
                for key in ("title", "value"):
                    if isinstance(fact.get(key), str):
                        result.append(fact[key])
        for child in value.values():
            result.extend(_texts(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_texts(child))
        return result
    return []


class RiskCollection:
    """Mongo collection double recording the active-risk query."""

    def __init__(self, document=None):
        self.document = document
        self.query = None

    async def find_one(self, query):
        self.query = query
        return self.document


@pytest.mark.asyncio
async def test_risk_repository_queries_active_risk_and_hides_mongo_id():
    collection = RiskCollection({
        "_id": "mongo-id",
        "risk_id": "RSK-1",
        "is_active": True,
        "title": "Stored title",
    })

    risk = await RiskRepository(collection=collection).get_by_risk_id("RSK-1")

    assert collection.query == {"risk_id": "RSK-1", "is_active": True}
    assert risk == {
        "risk_id": "RSK-1",
        "is_active": True,
        "title": "Stored title",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("document", [None, {"risk_id": "RSK-1", "is_active": False}])
async def test_risk_service_rejects_unknown_or_inactive_risk(document):
    with pytest.raises(AppError) as error:
        await RiskService(RiskRepository(collection=RiskCollection(document))).get(" RSK-1 ")

    assert error.value.code == "RISK_NOT_FOUND"
    assert error.value.status_code == 404


def test_renderer_handles_dynamic_blocks_and_preserves_order(caplog):
    renderer = TeamsRiskCardRenderer()
    risk = {
        "_id": "must-not-render",
        "risk_id": "RSK-1",
        "severity": "high",
        "title": "Stored title",
        "subtitle": "Stored subtitle",
        "summary": "Stored summary",
        "unknown_field": {"secret": "must-not-render"},
        "views": {"notification": {"blocks": [
            {"type": "key_value", "title": "Snapshot", "items": [
                {"label": "Warehouse", "value": "East"},
            ]},
            {"type": "metrics", "columns": [
                {"key": "label", "label": "Metric"},
                {"key": "value", "label": "Value"},
                {"key": "status", "label": "Status"},
            ], "items": [
                {"label": "Demand", "value": "500", "status": "high"},
                {"label": "Stock", "value": "100", "status": "low"},
                {"label": "Lead time", "value": "7 days", "status": "unknown"},
            ]},
            {"type": "text", "title": "Note", "text": "Review required", "bold": True},
            {"type": "table", "columns": [
                {"key": "warehouse", "label": "Location"},
                {"key": "stock", "label": "Available"},
            ], "rows": [
                {"warehouse": "East", "stock": "100"},
                {"warehouse": "West", "stock": "250"},
            ]},
            {"type": "action_list", "items": [
                {"order": 1, "title": "Review demand"},
                {"order": 2, "title": "Contact supplier"},
                {"order": 3, "title": "Update forecast"},
            ]},
            {"type": "chart", "data": {"secret": "ignored"}},
        ]}},
    }

    with caplog.at_level("WARNING"):
        card = renderer.render_notification(risk)

    serialized = json.dumps(card)
    texts = _texts(card)
    assert card["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert card["content"]["version"] == "1.4"
    assert all(value in texts for value in (
        "HIGH", "Stored title", "Stored subtitle", "Stored summary",
        "Snapshot", "Warehouse", "East", "Demand", "500", "Lead time",
        "Review required", "East", "100", "West", "250",
        "1. Review demand", "2. Contact supplier", "3. Update forecast",
    ))
    assert texts.index("Stored title") < texts.index("Snapshot") < texts.index("Review required")
    assert "must-not-render" not in serialized
    assert "unsupported_risk_card_block" in caplog.text


def test_renderer_supports_changed_table_keys_without_code_changes():
    renderer = TeamsRiskCardRenderer()
    card = renderer.render_notification({
        "risk_id": "RSK-2",
        "views": {"notification": {"blocks": [{
            "type": "table",
            "columns": [
                {"key": "customer_segment", "label": "Segment"},
                {"key": "exposure", "label": "Exposure"},
            ],
            "rows": [{"customer_segment": "Enterprise", "exposure": "$90k"}],
        }]}}
    })

    texts = _texts(card)
    assert "Enterprise" in texts
    assert "$90k" in texts
    assert "Segment" in texts
    assert "Exposure" in texts


def test_renderer_degrades_gracefully_for_missing_optional_fields():
    card = TeamsRiskCardRenderer().render_notification({
        "risk_id": "RSK-3",
        "is_active": True,
        "extra_field": "ignored",
    })

    assert card["content"]["body"] == []
    assert "None" not in json.dumps(card)
