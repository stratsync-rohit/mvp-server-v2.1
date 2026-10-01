"""Tests for the public read-only risk APIs."""

from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.repositories.risk_repository import RiskRepository
from src.services.risk_service import RiskService


class RiskCollection:
    """Small async Mongo collection double for API integration tests."""

    def __init__(self, documents):
        self.documents = documents

    def find(self, query):
        return [
            document for document in self.documents
            if all(document.get(field) == value for field, value in query.items())
        ]

    async def find_one(self, query):
        return next(
            (
                document for document in self.documents
                if all(document.get(field) == value for field, value in query.items())
            ),
            None,
        )


def _client(risks):
    app = create_app()
    app.state.container = Container(
        adapter=object(),
        bot=object(),
        risk_service=RiskService(RiskRepository(collection=RiskCollection(risks))),
    )
    return TestClient(app)


def test_list_risks_returns_empty_list_when_database_is_empty():
    response = _client([]).get("/api/risks")

    assert response.status_code == 200
    assert response.json() == []


def test_list_risks_returns_multiple_database_records_without_mongo_id():
    risks = [
        {"_id": "mongo-1", "risk_id": "RSK-1", "is_active": True, "title": "First"},
        {"_id": "mongo-2", "risk_id": "RSK-2", "is_active": True, "title": "Second"},
    ]

    response = _client(risks).get("/api/risks")

    assert response.status_code == 200
    assert response.json() == [
        {"risk_id": "RSK-1", "is_active": True, "title": "First"},
        {"risk_id": "RSK-2", "is_active": True, "title": "Second"},
    ]


def test_get_risk_returns_record_by_logical_risk_id():
    response = _client([
        {"_id": "mongo-1", "risk_id": "RSK-EFRY-O0QT", "is_active": True, "title": "Stored risk"},
    ]).get("/api/risks/RSK-EFRY-O0QT")

    assert response.status_code == 200
    assert response.json() == {
        "risk_id": "RSK-EFRY-O0QT",
        "is_active": True,
        "title": "Stored risk",
    }


def test_get_missing_risk_returns_404():
    response = _client([]).get("/api/risks/RSK-MISSING")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RISK_NOT_FOUND"
