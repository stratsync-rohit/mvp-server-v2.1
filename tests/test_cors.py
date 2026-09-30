"""Tests for the application-wide trusted-origin CORS policy."""

from fastapi.testclient import TestClient

from src.api.dependencies import Container
from src.application import create_app
from src.config.settings import Settings
from src.schemas.installation import InstallationResponse


ALLOWED_ORIGIN = "http://localhost:3000"


def _app_with_installations():
    class InstallationServiceDouble:
        async def list_installations(self):
            return [
                InstallationResponse(
                    tenant_id="tenant-a",
                    team_id="team-1",
                    team_name="Bot test",
                    channels=[],
                )
            ]

    app = create_app()
    app.state.container = Container(
        adapter=object(), bot=object(), installation_service=InstallationServiceDouble()
    )
    return app


def _preflight(client: TestClient, path: str, method: str = "GET"):
    return client.options(
        path,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_cors_setting_trims_and_ignores_empty_origins():
    settings = Settings(
        _env_file=None,
        CORS_ALLOWED_ORIGINS=" http://frontend.example , , http://admin.example ",
    )

    assert settings.cors_allowed_origins == [
        "http://frontend.example",
        "http://admin.example",
    ]


def test_allowed_get_preflight_succeeds_with_explicit_origin():
    response = _preflight(TestClient(_app_with_installations()), "/api/installations")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_allowed_get_includes_cors_header():
    response = TestClient(_app_with_installations()).get(
        "/api/installations", headers={"Origin": ALLOWED_ORIGIN}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_allowed_origin_can_preflight_each_post_api():
    client = TestClient(create_app())

    for path in (
        "/api/messages",
        "/api/destinations/resolve",
        "/api/notifications/send",
    ):
        response = _preflight(client, path, method="POST")

        assert response.status_code == 200, path
        assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_unconfigured_origin_is_not_granted_cors_access():
    response = TestClient(_app_with_installations()).options(
        "/api/installations",
        headers={
            "Origin": "http://unconfigured.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers
