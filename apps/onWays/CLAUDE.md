# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (requires Redis)
cp .env.example .env          # then fill in values
docker-compose up redis       # start Redis only
uvicorn app.main:app --reload

# Full stack (app + Redis)
docker-compose up

# Tests (no Redis needed — uses fakeredis)
python3.11 -m pytest                          # all tests
python3.11 -m pytest tests/test_parsers.py -v # single file
python3.11 -m pytest -k "test_ban"            # filter by name
```

`pytest.ini` sets `asyncio_mode = auto` — no `@pytest.mark.asyncio` needed on test functions.

## Architecture

OnWays is a **WhatsApp API gateway** with two jobs:

1. **Ingest** heterogeneous webhooks from WAHA (unofficial) and Meta Cloud API, normalise them into a single `UnifiedMessage` / `UnifiedReadReceipt` schema, and forward to a downstream CRM.
2. **Route outbound messages** from the CRM, with automatic silent failover from WAHA to Meta when WAHA is banned.

### Inbound flow (`POST /v1/webhooks/{provider}`)

```
raw body bytes
  → Meta HMAC verify (if provider==meta && META_APP_SECRET set)
  → JSON parse
  → Parser selection  (Strategy Pattern: WahaWebhookParser | MetaCloudWebhookParser)
  → Normalise         (→ UnifiedMessage or UnifiedReadReceipt)
  → Redis idempotency (SET NX EX 24h on "idempotency:{message_id}")
  → Mark conversation window  ("meta:conv_window:{from_number}" with 24h TTL)
  → CrmForwarder.forward()    (fire-and-forget; retries; dead-letter on failure)
  → return 200 + unified JSON
```

### Outbound flow (`POST /v1/messages`)

```
API key check (X-Api-Key, skipped if GATEWAY_API_KEY="")
  → Read "routing:state:{session_id}" from Redis
  → NORMAL: try WahaClient.send_text()
      success → return waha response
      BanDetectedError → set state BANNED → retry via Meta (failover_triggered=true)
      ProviderError (non-ban) → surface 503
  → BANNED: check is_ban_expired()
      not expired → send via MetaCloudClient
      expired → probe WahaClient.health_check()
        OK → set state NORMAL → send via WAHA
        FAIL → reset ban TTL → send via Meta
```

**Meta message mode selection** (when routing via Meta):
- `meta:conv_window:{customer}` exists → free-form text (customer messaged us within 24h)
- key absent → pre-approved template only (Meta policy for cold outreach)

### Key patterns

**Strategy Pattern — parsers** (`app/parsers/`):
- Interface: `IWebhookParser` with `can_parse(payload) → bool` and `parse(payload) → ParsedEvent`
- The router calls `can_parse()` down the list; first match wins
- To add a provider: implement `IWebhookParser`, register in `_PARSERS` in `routers/webhooks.py`

**Strategy Pattern — channel clients** (`app/clients/`):
- Interface: `IChannelClient` with `send_text()`, `send_template()`, `health_check()`
- `BanDetectedError` triggers failover; `ProviderError` surfaces to CRM without failover

**Dependency injection via `app.state`** (`app/main.py` startup):
- All singletons (`RedisClient`, `StateManager`, `MessageRouter`, `CrmForwarder`) are created once and stored on `app.state`
- Endpoints retrieve them via `request.app.state.*`
- Tests patch `RedisClient.__init__` to inject `fakeredis.aioredis.FakeRedis`, then override `app.state.message_router._waha` / `._meta` after startup

### Redis key namespace

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `idempotency:{message_id}` | string | 24h | Dedup inbound webhooks |
| `meta:conv_window:{number}` | string | 24h | Track 24h Meta free-form eligibility |
| `routing:state:{session_id}` | string (JSON) | none | Ban state (`{state, banned_at, expires_at}`) |
| `crm:dead_letter` | list (LPUSH) | none | Failed CRM forwards, capped at 200 |

### Channel state machine

```
NORMAL ──(BanDetectedError)──→ BANNED
BANNED ──(ban TTL expired + health_check OK)──→ NORMAL
BANNED ──(ban TTL expired + health_check FAIL)──→ BANNED (TTL reset)
any ──(POST /v1/admin/state/{sid}/reset or /ban)──→ NORMAL or BANNED
```

`BAN_RECOVERY_SECONDS` (default 86400) sets how long before a probe is attempted. Set to 60 in dev for fast failover testing.

### Security layers

| Layer | Header | Env var | Enforced on | Skipped when |
|-------|--------|---------|-------------|--------------|
| Meta webhook HMAC | `X-Hub-Signature-256` | `META_APP_SECRET` | `POST /v1/webhooks/meta` | var is blank |
| Gateway API key | `X-Api-Key` | `GATEWAY_API_KEY` | `/v1/messages`, `/v1/admin/*` | var is blank |
| CRM forward HMAC | `X-Onways-Signature` | `CRM_WEBHOOK_SECRET` | CrmForwarder POSTs | var is blank |

All three default to disabled in dev (blank var). All three log a warning when unconfigured.

### Logging

`CorrelationIdMiddleware` generates/propagates `X-Request-Id` per request and echoes it in the response. `RequestIdFilter` injects `request_id` into every log record (format: `%(asctime)s | %(levelname)s | [%(request_id)s] | %(name)s | %(message)s`).

### Settings

`app/core/config.py` uses `pydantic-settings`. The singleton is `get_settings()` (LRU-cached). Tests call `get_settings.cache_clear()` before setting env vars — this is handled by the `clear_settings_cache` autouse fixture in `tests/conftest.py`.

### Admin endpoints (`/v1/admin/`, requires API key)

- `GET  /state/{session_id}` — inspect current routing state + ban timestamps
- `POST /state/{session_id}/reset` — force NORMAL (manual ban recovery)
- `POST /state/{session_id}/ban` — force BANNED (maintenance / testing)
- `GET  /dead-letter?limit=N` — inspect failed CRM forward queue
- `GET  /health` — Redis ping + default session state

### Integration test pattern

Integration tests use `starlette.testclient.TestClient` (sync, handles lifespan). Redis is replaced by patching `RedisClient.__init__` to inject a `fakeredis.aioredis.FakeRedis` instance. Channel clients are replaced by overriding `app.state.message_router._waha` / `._meta` with `AsyncMock` after the `with TestClient(app)` context starts (lifespan has already run at that point). Never use `asyncio.get_event_loop().run_until_complete()` inside sync test functions — use the admin API endpoints instead to drive state changes within TestClient's own event loop.
