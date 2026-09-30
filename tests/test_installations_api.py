"""Tests for the safe Teams installations read API."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.schemas.installation import InstallationResponse
from src.services.installation_service import InstallationService


def _installation(tenant_id: str, team_id: str) -> dict:
    """Build a persistence-shaped installation fixture."""
    timestamp = datetime(2026, 9, 29, tzinfo=timezone.utc)
    return {
        "_id": "must-not-leak",
        "tenant_id": tenant_id,
        "team_id": team_id,
        "team_name": f"Team {team_id}",
        "conversation_id": f"conversation-{team_id}",
        "service_url": "https://smba.example",
        "is_active": True,
        "installed_at": timestamp,
        "updated_at": timestamp,
        "uninstalled_at": None,
        "microsoft_app_password": "must-not-leak",
    }


def _channel(tenant_id: str, team_id: str, channel_id: str) -> dict:
    """Build a persistence-shaped channel fixture."""
    timestamp = datetime(2026, 9, 29, tzinfo=timezone.utc)
    return {
        "_id": "must-not-leak",
        "tenant_id": tenant_id,
        "team_id": team_id,
        "channel_id": channel_id,
        "channel_name": f"Channel {channel_id}",
        "team_name": f"Team {team_id}",
        "conversation_id": f"conversation-{team_id}",
        "service_url": "https://smba.example",
        "available": True,
        "discovered_at": timestamp,
        "updated_at": timestamp,
        "access_token": "must-not-leak",
    }


def _aggregated_service() -> InstallationService:
    class InstallationRepository:
        async def list_all(self):
            return [_installation("tenant-a", "team-1"), _installation("tenant-b", "team-1")]

    class ChannelRepository:
        async def list_for_team(self, tenant_id, team_id):
            return [_channel(tenant_id, team_id, f"channel-{tenant_id}")]

    return InstallationService(InstallationRepository(), object(), ChannelRepository())


def test_installations_service_groups_channels_by_tenant_and_team():
    import asyncio

    data = asyncio.run(_aggregated_service().list_installations())

    assert len(data) == 2
    assert data[0].team_name == "Team team-1"
    assert data[0].channels[0].tenant_id == "tenant-a"
    assert data[1].channels[0].tenant_id == "tenant-b"
    assert data[0].channels[0].channel_id != data[1].channels[0].channel_id


def test_installations_service_without_channel_repository_still_returns_installations():
    import asyncio

    class InstallationRepository:
        async def list_all(self):
            return [_installation("tenant-a", "team-1")]

    data = asyncio.run(
        InstallationService(InstallationRepository(), object()).list_installations()
    )

    assert len(data) == 1
    assert data[0].team_name == "Team team-1"
    assert data[0].channels == []


def test_get_installations_returns_safe_enveloped_data():
    class InstallationServiceDouble:
        async def list_installations(self):
            return [InstallationResponse(**{
                "tenant_id": "tenant-a", "team_id": "team-1", "team_name": "Bot test",
                "channels": [],
            })]

    app = create_app()
    app.state.container = Container(
        adapter=object(), bot=object(), installation_service=InstallationServiceDouble()
    )
    response = TestClient(app).get("/api/installations")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"][0]["team_name"] == "Bot test"
    assert body["data"][0]["channels"] == []
    assert body["error"] is None

    def keys(value):
        if isinstance(value, dict):
            return set(value) | {key for child in value.values() for key in keys(child)}
        if isinstance(value, list):
            return {key for child in value for key in keys(child)}
        return set()

    response_keys = keys(body)
    assert "_id" not in response_keys
    assert "microsoft_app_password" not in response_keys
    assert "access_token" not in response_keys


def test_get_installations_returns_empty_data_when_no_installations():
    class EmptyInstallationService:
        async def list_installations(self):
            return []

    app = create_app()
    app.state.container = Container(
        adapter=object(), bot=object(), installation_service=EmptyInstallationService()
    )
    response = TestClient(app).get("/api/installations")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": [], "error": None}
