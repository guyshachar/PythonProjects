# CheerApp Backend

Standalone FastAPI service. Deliberately **not** wired into `shared/`'s
`AppContainer`/multi-tenant DI — CheerApp is an unrelated product to
RefPortal, not a referee-portal feature, so it doesn't need RefPortal's
tenancy, org services, or WhatsApp messaging stack. It follows this
repo's convention of "each service is an independent Docker image"
(see root `CLAUDE.md`), it just doesn't share RefPortal's domain code.

## Endpoints (v1 contract)

| Method | Path | Purpose |
|---|---|---|
| GET | `/time` | High-res server timestamp for client-side SNTP-style offset calc (`docs/SYNC_DESIGN.md`) |
| POST | `/events` | Create an Event |
| GET | `/events/{eventId}` | Fetch an Event (venue, zones, start time) |
| POST | `/events/{eventId}/shows` | Publish a Show (validated against `shared/show.schema.json`) |
| GET | `/events/{eventId}/show` | Fetch the current published Show + asset manifest |
| POST | `/events/{eventId}/checkin` | Client reports a scanned QR token -> resolved zone id |
| WS | `/events/{eventId}/live` | Control channel: go-live / delay / abort broadcasts |

## Status

Skeleton only — in-memory store, no auth, no persistence, no asset
upload/CDN yet. This exists to pin down the contract the web and iOS
prototypes are already coded against; swap `app/store.py` for a real
datastore before this leaves prototype status.

## Run locally

```bash
cd cheerApp/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 5100
```
