import { ApiClient } from "./apiClient.js";
import { TimeSync } from "./timeSync.js";
import { CueEngine, flashRenderer, colorRenderer, imageRenderer, videoRenderer, mediaRenderer } from "./cueEngine.js";
import { WakeLockKeeper } from "./wakeLock.js";
import { AssetStore } from "./assetStore.js";
import { SUPPORTED_LANGS, applyLangToDocument, detectLang, saveLang, t } from "./i18n.js";

// Real join flow: open this page as
//   index.html?event=<eventId>&qr=<qrToken>
// `qr` comes from the venue's zone QR code and is optional — without it
// you join as zone "ALL": an unscanned viewer still gets whole-venue
// cues, just not zone-scoped ones (cueEngine.js's zone filter), which is
// the correct fail-safe per docs/ARCHITECTURE.md §3.
//
// All of the show's assets (image/video/audio) are downloaded and primed
// — see assetStore.js — before the CueEngine ever starts. If any asset
// fails to download or fails its integrity check, main() throws and the
// join aborts with an error rather than starting a show some cues can't
// actually render — see docs/ARCHITECTURE.md §5.
//
// A "Tap to join" gate blocks starting the engine (not the setup work
// before it — that runs immediately) because Chrome/Safari refuse
// audio/video autoplay-with-sound until the page has seen a user
// gesture; without it, every video/audio cue silently no-ops at fire
// time with no network to blame — confirmed via a live-browser test
// (NotAllowedError from a bare page-load with no click).

const API_BASE = window.CHEERAPP_API_BASE || "http://localhost:5100";
const SHOW_POLL_INTERVAL_MS = 5000;

const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");

// Language: applied before anything else runs, so RTL layout (Hebrew)
// and the join button's text are correct from first paint, not just
// after async setup. See i18n.js for the en/he→default resolution order.
const lang = detectLang();
applyLangToDocument(lang);
document.title = t(lang, "pageTitle");
document.getElementById("joinBtn").textContent = t(lang, "joinBtn");
initLangSwitch(lang);
setStatus(t(lang, "loading"));

function setStatus(text) {
  statusEl.textContent = text;
}

/** Wires the EN/עב buttons: picking one saves it as the user's default
 * (this feature's actual ask) and reloads with ?lang= set explicitly,
 * preserving event/qr — simplest correct way to re-render every
 * already-emitted status string in the new language. */
function initLangSwitch(currentLang) {
  for (const btn of document.querySelectorAll("#langSwitch button")) {
    const btnLang = btn.dataset.lang;
    btn.setAttribute("aria-pressed", String(btnLang === currentLang));
    if (!SUPPORTED_LANGS.includes(btnLang)) continue;
    btn.addEventListener("click", () => {
      saveLang(btnLang);
      const url = new URL(window.location.href);
      url.searchParams.set("lang", btnLang);
      window.location.href = url.toString();
    });
  }
}

function getParams() {
  const params = new URLSearchParams(window.location.search);
  return { eventId: params.get("event"), qrToken: params.get("qr") };
}

/** Resolves on the first tap of the join gate — starts listening
 * immediately so it can resolve while setup work is still in flight. */
function waitForTap() {
  return new Promise((resolve) => {
    document.getElementById("joinBtn").addEventListener("click", () => resolve(), { once: true });
  });
}

function removeJoinGate() {
  document.getElementById("joinGate")?.remove();
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

/** Attaches primed video elements to the stage (visible, initially
 * transparent — videoRenderer toggles opacity per cue) and audio
 * elements to a hidden host. Assets with no matching cue type still get
 * a <video>/<audio> element from AssetStore; harmless, just unused. */
function attachMediaElements(assetStore, assets) {
  const audioHost = document.createElement("div");
  audioHost.style.display = "none";
  document.body.appendChild(audioHost);

  for (const asset of assets) {
    const entry = assetStore.get(asset.assetId);
    if (!entry?.mediaEl) continue;
    if (asset.type === "video") {
      entry.mediaEl.style.cssText =
        "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity 40ms linear;";
      stage.appendChild(entry.mediaEl);
    } else {
      audioHost.appendChild(entry.mediaEl);
    }
  }
}

async function main() {
  const { eventId, qrToken } = getParams();
  if (!eventId) {
    removeJoinGate();
    setStatus(t(lang, "noEvent"));
    return;
  }

  const tapped = waitForTap(); // listening now; awaited later, right before anything needs to autoplay

  const api = new ApiClient(API_BASE);

  setStatus(t(lang, "joiningEvent"));
  const event = await api.getEvent(eventId); // throws (and aborts main()) if the event doesn't exist

  setStatus(t(lang, "joined", event.name));
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
      setStatus(t(lang, "qrNotRecognized"));
    }
  }

  await timeSyncStarted;
  setStatus(t(lang, "syncedWaitingShow", zoneId, Math.round(timeSync.confidenceMs)));

  const show = await waitForShow(api, eventId, () => setStatus(t(lang, "waitingForPublish", zoneId)));

  const assetStore = new AssetStore();
  setStatus(t(lang, "downloadingAssets", zoneId));
  await assetStore.preload(show.assets, (done, total) => {
    if (total > 0) setStatus(t(lang, "downloadingAssetsProgress", zoneId, done, total));
  });
  attachMediaElements(assetStore, show.assets);

  setStatus(t(lang, "readyTap", zoneId));
  await tapped;
  removeJoinGate();

  const wakeLock = new WakeLockKeeper();
  await wakeLock.start();

  const mediaElFor = (assetId) => assetStore.get(assetId)?.mediaEl;
  let wasBackgrounded = false;
  const engine = new CueEngine(show, timeSync, {
    zoneId,
    renderers: {
      flash: flashRenderer(stage),
      color: colorRenderer(stage),
      image: imageRenderer(stage, (assetId) => assetStore.get(assetId)?.objectUrl),
      video: videoRenderer(mediaElFor),
      audio: mediaRenderer(mediaElFor),
    },
    onVisibilityChange: (hidden) => {
      if (hidden) {
        wasBackgrounded = true;
      } else if (wasBackgrounded) {
        setStatus(t(lang, "backgroundedWarning"));
      }
    },
  });

  const startAtMs = Date.parse(show.startAtUtc);
  const foregroundReminder = t(lang, "foregroundReminder");
  let countdownTimer = null;
  const updateCountdown = () => {
    const untilStartMs = startAtMs - timeSync.serverNow();
    if (untilStartMs <= 0) {
      setStatus(t(lang, "showLive", zoneId, foregroundReminder));
      clearInterval(countdownTimer);
      return;
    }
    setStatus(t(lang, "showStartsIn", zoneId, Math.ceil(untilStartMs / 1000), foregroundReminder));
  };
  countdownTimer = setInterval(updateCountdown, 1000);
  updateCountdown();

  engine.start();

  window.addEventListener("beforeunload", () => {
    clearInterval(countdownTimer);
    engine.stop();
    timeSync.stop();
    wakeLock.stop();
    assetStore.clear();
  });
}

main().catch((err) => {
  removeJoinGate();
  setStatus(t(lang, "errorPrefix", err.message));
  console.error(err);
});
