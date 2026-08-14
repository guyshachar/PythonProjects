import { TimeSync } from "./timeSync.js";
import { CueEngine, flashRenderer, colorRenderer } from "./cueEngine.js";

// Demo wiring only — no real join/QR/zone flow yet, see cheerApp/docs/ROADMAP.md
// Phase 1. Point TIME_ENDPOINT at a running cheerApp/backend instance
// (`uvicorn app.main:app --port 5100` from cheerApp/backend/) to try it live.

const TIME_ENDPOINT = window.CHEERAPP_TIME_ENDPOINT || "http://localhost:5100/time";
const stage = document.getElementById("stage");
const statusEl = document.getElementById("status");

async function main() {
  const timeSync = new TimeSync(TIME_ENDPOINT);
  statusEl.textContent = "Syncing clock…";
  await timeSync.start();
  statusEl.textContent = `Synced (±${Math.round(timeSync.confidenceMs)}ms)`;

  // A tiny demo show: a 3s flash starting 5s from now, then a red flash 2s after.
  const now = timeSync.serverNow();
  const demoShow = {
    startAtUtc: new Date(now).toISOString(),
    cues: [
      { id: "demo-flash", offsetMs: 5000, durationMs: 3000, type: "flash", params: { frequencyHz: 5 }, zones: ["ALL"] },
      { id: "demo-color", offsetMs: 10000, durationMs: 2000, type: "color", params: { hex: "#ff0000" }, zones: ["ALL"] },
    ],
  };

  const engine = new CueEngine(demoShow, timeSync, {
    zoneId: "ALL",
    renderers: {
      flash: flashRenderer(stage),
      color: colorRenderer(stage),
    },
  });
  engine.start();
  statusEl.textContent += " — demo show scheduled, watch the stage.";
}

main().catch((err) => {
  statusEl.textContent = `Error: ${err.message}`;
  console.error(err);
});
