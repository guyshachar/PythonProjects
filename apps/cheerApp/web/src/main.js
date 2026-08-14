import { ApiClient } from "./apiClient.js";
import { TimeSync } from "./timeSync.js";
import { CueEngine, flashRenderer, colorRenderer } from "./cueEngine.js";
import { WakeLockKeeper } from "./wakeLock.js";

// Real join flow: open this page as
//   index.html?event=<eventId>&qr=<qrToken>
// `qr` comes from the venue's zone QR code and is optional — without it
// you join as zone "ALL": an unscanned viewer still gets whole-venue
// cues, just not zone-scoped ones (cueEngine.js's zone filter), which is
// the correct fail-safe per docs/ARCHITECTURE.md §3. No asset pre-fetch/CDN yet
// (docs/ROADMAP.md Phase 1), so only flash/color cues render for real —
// image/video/audio cues log a warning and are otherwise silently
// skipped (CueEngine's existing missing-renderer fallback).

const API_BASE = window.CHEERAPP_API_BASE || "http://localhost:5100";
const SHOW_POLL_INTERVAL_MS = 5000;

const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");

function setStatus(text) {
  statusEl.textContent = text;
}

function getParams() {
  const params = new URLSearchParams(window.location.search);
  return { eventId: params.get("event"), qrToken: params.get("qr") };
}

/** Poll GET .../show until the producer has published one. */
async function waitForShow(api, eventId, onWaiting) {
  for (;;) {
    const show = await api.getShow(eventId);
    if (show) return show;
    onWaiting();
    await new Promise((resolve) => setTimeout(resolve, SHOW_POLL_INTERVAL_MS));
  }
}

async function main() {
  const { eventId, qrToken } = getParams();
  if (!eventId) {
    setStatus("No event specified — open this page via your event's join link (?event=...).");
    return;
  }

  const api = new ApiClient(API_BASE);

  setStatus("Joining event…");
  const event = await api.getEvent(eventId); // throws (and aborts main()) if the event doesn't exist

  setStatus(`Joined "${event.name}" — syncing clock…`);
  const timeSync = new TimeSync(`${API_BASE}/time`);
  const timeSyncStarted = timeSync.start();

  let zoneId = "ALL";
  if (qrToken) {
    try {
      const { zoneId: resolved } = await api.checkin(eventId, qrToken);
      zoneId = resolved;
    } catch {
      // Unrecognized/expired QR token — fall back to ALL rather than
      // blocking the join; the fan still sees whole-venue cues.
      setStatus("QR code not recognized for this event — continuing without a zone.");
    }
  }

  await timeSyncStarted;
  setStatus(`Zone: ${zoneId} — synced (±${Math.round(timeSync.confidenceMs)}ms) — waiting for the show…`);

  const show = await waitForShow(api, eventId, () =>
    setStatus(`Zone: ${zoneId} — synced — waiting for the producer to publish the show…`)
  );

  const wakeLock = new WakeLockKeeper();
  await wakeLock.start();

  let wasBackgrounded = false;
  const engine = new CueEngine(show, timeSync, {
    zoneId,
    renderers: {
      flash: flashRenderer(stage),
      color: colorRenderer(stage),
    },
    onVisibilityChange: (hidden) => {
      if (hidden) {
        wasBackgrounded = true;
      } else if (wasBackgrounded) {
        setStatus("You were backgrounded — some cues may have been missed. Keep CheerApp open and foregrounded.");
      }
    },
  });

  const startAtMs = Date.parse(show.startAtUtc);
  const foregroundReminder = "Keep this screen on and CheerApp in the foreground.";
  let countdownTimer = null;
  const updateCountdown = () => {
    const untilStartMs = startAtMs - timeSync.serverNow();
    if (untilStartMs <= 0) {
      setStatus(`Zone: ${zoneId} — show is live. ${foregroundReminder}`);
      clearInterval(countdownTimer);
      return;
    }
    setStatus(`Zone: ${zoneId} — show starts in ${Math.ceil(untilStartMs / 1000)}s. ${foregroundReminder}`);
  };
  countdownTimer = setInterval(updateCountdown, 1000);
  updateCountdown();

  engine.start();

  window.addEventListener("beforeunload", () => {
    clearInterval(countdownTimer);
    engine.stop();
    timeSync.stop();
    wakeLock.stop();
  });
}

main().catch((err) => {
  setStatus(`Error: ${err.message}`);
  console.error(err);
});
