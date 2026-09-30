from types import SimpleNamespace

import pytest
from botbuilder.core.teams import TeamsActivityHandler
from fastapi.testclient import TestClient

import src.application as application_module
from src.api.dependencies import Container
from src.application import create_app
from src.bot.handlers.risk_bot import RiskBot


class RecordingAdapter:
    def __init__(self) -> None:
        self.calls = []

    async def process_activity(self, auth_header, activity, callback):
        self.calls.append((auth_header, activity, callback))
        return None


class StubBot:
    async def on_turn(self, turn_context):
        return None


def test_health_and_readiness_are_dependency_free():
    client = TestClient(create_app())

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_application_route_inventory_is_minimal():
    app = create_app()
    application_routes = {
        (method, route.path)
        for route in app.routes
        for method in (route.methods or set())
        if route.path in {"/health", "/ready", "/api/messages"}
    }

    assert application_routes == {
        ("GET", "/health"),
        ("GET", "/ready"),
        ("POST", "/api/messages"),
    }


def test_messages_route_deserializes_and_delegates_with_authorization_header():
    app = create_app()
    adapter = RecordingAdapter()
    bot = StubBot()
    app.state.container = Container(adapter=adapter, bot=bot)
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        },
        json={
            "type": "message",
            "id": "activity-1",
            "channelId": "msteams",
            "serviceUrl": "https://smba.trafficmanager.net/emea/",
            "conversation": {"id": "conversation-1"},
            "from": {"id": "user-1"},
            "recipient": {"id": "bot-1"},
            "text": "hello",
        },
    )

    assert response.status_code == 201
    assert len(adapter.calls) == 1
    auth_header, activity, callback = adapter.calls[0]
    assert auth_header == "Bearer test-token"
    assert activity.type == "message"
    assert activity.id == "activity-1"
    assert callback.__self__ is bot


@pytest.mark.asyncio
async def test_lifespan_wires_adapter_and_minimal_bot(monkeypatch):
    adapter = RecordingAdapter()
    monkeypatch.setattr(application_module, "create_adapter", lambda settings: adapter)
    app = create_app()

    async with app.router.lifespan_context(app):
        assert app.state.container.adapter is adapter
        assert isinstance(app.state.container.bot, RiskBot)


@pytest.mark.asyncio
async def test_risk_bot_delegates_to_sdk_dispatch(monkeypatch):
    calls = []

    async def sdk_on_turn(self, turn_context):
        calls.append(turn_context)

    monkeypatch.setattr(TeamsActivityHandler, "on_turn", sdk_on_turn)
    context = SimpleNamespace(
        activity=SimpleNamespace(type="conversationUpdate", id="activity-2")
    )

    await RiskBot().on_turn(context)

    assert calls == [context]
