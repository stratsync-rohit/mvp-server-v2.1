# Enterprise Risk Bot: Learning Baseline

A deliberately minimal Microsoft Teams bot backend built with FastAPI and the
Microsoft Bot Framework Python SDK. This baseline exists to make the inbound
Teams activity lifecycle easy to understand before business features are added
back one at a time.

## Runtime responsibilities

The application currently does only four things:

1. starts FastAPI;
2. creates an authenticated Bot Framework `CloudAdapter`;
3. accepts Bot Framework activities at `POST /api/messages`;
4. delegates activities to a minimal `TeamsActivityHandler`.

The internal architecture includes MongoDB-backed installation/channel/routing
state, notification and reaction services, safe activity diagnostics, and
retry-safe activity idempotency. These capabilities remain internal to the bot
activity flow, plus the read-only installation inventory API.

## Request flow

```text
Microsoft Teams / Azure Bot Service
                ↓
        POST /api/messages
                ↓
       deserialize Activity
                ↓
      read Authorization header
                ↓
 CloudAdapter.process_activity(...)
                ↓
     RiskBot → SDK activity dispatch
```

`CloudAdapter` authentication remains enabled. The application never logs the
Authorization header.

## Application routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Process liveness |
| `GET` | `/ready` | Minimal application readiness |
| `POST` | `/api/messages` | Authenticated Bot Framework activities |
| `GET` | `/api/installations` | Read-only Teams installation inventory |

FastAPI documentation remains available at `/docs`, `/redoc`, and
`/openapi.json`.

## Source structure

```text
src/
├── main.py
├── application.py
├── api/
│   ├── bot_routes.py
│   ├── dependencies.py
│   └── health_routes.py
├── bot/
│   ├── adapter.py
│   └── handlers/
│       └── risk_bot.py
├── config/
│   └── settings.py
├── middleware/
│   └── request_logging.py
├── schemas/
│   └── health.py
├── utils/
│   └── logger.py
└── exceptions.py
```

## Configuration

Copy the example environment file and provide the values from the existing
Microsoft Entra/Azure Bot registration:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `MICROSOFT_APP_ID` | Bot application ID |
| `MICROSOFT_APP_PASSWORD` | Bot client secret |
| `MICROSOFT_APP_TENANT_ID` | Single-tenant Entra tenant ID |
| `MICROSOFT_APP_TYPE` | Expected to be `SingleTenant` |
| `LOG_LEVEL` | Application logging level |
| `CORS_ALLOWED_ORIGINS` | Comma-separated trusted browser origins; defaults to the two localhost:3000 origins |

The Azure Bot messaging endpoint remains:

```text
https://YOUR_PUBLIC_HOST/api/messages
```

Do not place secrets in source control.

## Docker-first workflow

```bash
docker compose build backend
docker compose run --rm backend python -m compileall src
docker compose run --rm backend pytest -q
docker compose up -d --build
```

The production command is:

```bash
uvicorn src.main:app --host 0.0.0.0 --port 3978
```

Check the running application:

```bash
curl -s http://localhost:3978/health
curl -s http://localhost:3978/ready
```

Expected responses:

```json
{"status":"ok"}
```

```json
{"status":"ready"}
```

The previous Mongo volume is intentionally not referenced by this baseline.
Do not run `docker compose down -v`; historical data remains available for a
later learning step.

## Internal persistence

MongoDB is started by Docker Compose with the named `mongodb_data` volume.
Application collections are `teams_installations`,
`teams_discovered_channels`, `destinations`, `notifications`,
`notification_reactions`, and `processed_activities`. Do not run
`docker compose down -v`; existing Mongo data must remain recoverable.

Set `TEAMS_DEBUG_ACTIVITY_LOGGING=true` only for development diagnostics. Raw
activities are sanitized before debug logging, and Authorization headers and
credentials are never logged.

## Tests

The focused test suite verifies:

- health and readiness responses;
- the exact application route inventory;
- `/api/messages` Activity deserialization and adapter delegation;
- lifespan wiring of `CloudAdapter` and `RiskBot`;
- delegation from `RiskBot` to SDK activity dispatch.

No test fakes Microsoft authentication as an application feature. The route
passes the real Authorization header to `CloudAdapter.process_activity`, where
the Bot Framework authentication pipeline handles it in production.
