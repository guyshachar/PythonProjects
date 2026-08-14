/**
 * i18n for the fan-facing join flow (main.js's status text, the join
 * button, the page title). Two languages for now — en/he — chosen for
 * the language switcher's own UI too, not just content.
 *
 * Scope: the primary happy-path flow text authored in main.js. Lower-
 * level diagnostic errors thrown by timeSync.js/assetStore.js/
 * apiClient.js (e.g. "sha256 mismatch", "only 3/8 samples succeeded")
 * stay in English — they're developer-facing failure detail shown in an
 * already-degraded error state, not core UX text worth duplicating
 * translation effort on right now.
 *
 * No build step (this repo's convention, see web/README.md), so no ICU
 * MessageFormat library — interpolated strings are just functions.
 */

const SUPPORTED_LANGS = ["en", "he"];
const DEFAULT_LANG = "en";
const STORAGE_KEY = "cheerapp:lang";

const translations = {
  en: {
    pageTitle: "CheerApp — Join the Show",
    loading: "Loading…",
    joinBtn: "Tap to join the show",
    noEvent: "No event specified — open this page via your event's join link (?event=...).",
    joiningEvent: "Joining event…",
    joined: (name) => `Joined "${name}" — syncing clock…`,
    qrNotRecognized: "QR code not recognized for this event — continuing without a zone.",
    syncedWaitingShow: (zoneId, ms) => `Zone: ${zoneId} — synced (±${ms}ms) — waiting for the show…`,
    waitingForPublish: (zoneId) => `Zone: ${zoneId} — synced — waiting for the producer to publish the show…`,
    downloadingAssets: (zoneId) => `Zone: ${zoneId} — downloading show assets…`,
    downloadingAssetsProgress: (zoneId, done, total) =>
      `Zone: ${zoneId} — downloading show assets (${done}/${total})…`,
    readyTap: (zoneId) => `Zone: ${zoneId} — ready. Tap to join the show.`,
    backgroundedWarning: "You were backgrounded — some cues may have been missed. Keep CheerApp open and foregrounded.",
    foregroundReminder: "Keep this screen on and CheerApp in the foreground.",
    showStartsIn: (zoneId, secs, reminder) => `Zone: ${zoneId} — show starts in ${secs}s. ${reminder}`,
    showLive: (zoneId, reminder) => `Zone: ${zoneId} — show is live. ${reminder}`,
    errorPrefix: (msg) => `Error: ${msg}`,
  },
  he: {
    pageTitle: "CheerApp — הצטרפות למופע",
    loading: "טוען…",
    joinBtn: "הקישו כדי להצטרף למופע",
    noEvent: "לא צויין אירוע — יש לפתוח דף זה דרך קישור ההצטרפות לאירוע (?event=...).",
    joiningEvent: "מצטרפים לאירוע…",
    joined: (name) => `הצטרפת ל-"${name}" — מסנכרן שעון…`,
    qrNotRecognized: "קוד ה-QR לא זוהה עבור אירוע זה — ממשיכים ללא אזור.",
    syncedWaitingShow: (zoneId, ms) => `אזור: ${zoneId} — סונכרן (±${ms}ms) — ממתין למופע…`,
    waitingForPublish: (zoneId) => `אזור: ${zoneId} — סונכרן — ממתין שהמפיק יפרסם את המופע…`,
    downloadingAssets: (zoneId) => `אזור: ${zoneId} — מוריד את קבצי המופע…`,
    downloadingAssetsProgress: (zoneId, done, total) =>
      `אזור: ${zoneId} — מוריד את קבצי המופע (${done}/${total})…`,
    readyTap: (zoneId) => `אזור: ${zoneId} — מוכן. הקישו כדי להצטרף למופע.`,
    backgroundedWarning: "האפליקציה עברה לרקע — ייתכן שהוחמצו כמה רגעים. יש להשאיר את CheerApp פתוחה וברקע הקדמי.",
    foregroundReminder: "יש להשאיר את המסך דלוק ואת CheerApp ברקע הקדמי.",
    showStartsIn: (zoneId, secs, reminder) => `אזור: ${zoneId} — המופע יתחיל בעוד ${secs} שניות. ${reminder}`,
    showLive: (zoneId, reminder) => `אזור: ${zoneId} — המופע פעיל עכשיו. ${reminder}`,
    errorPrefix: (msg) => `שגיאה: ${msg}`,
  },
};

/**
 * Resolution order: explicit ?lang= (lets a join link force a language),
 * then the user's saved default (this feature's actual ask), then the
 * browser's own language, then English.
 */
export function detectLang() {
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (SUPPORTED_LANGS.includes(fromUrl)) return fromUrl;

  const stored = localStorage.getItem(STORAGE_KEY);
  if (SUPPORTED_LANGS.includes(stored)) return stored;

  const browserLang = navigator.language?.slice(0, 2);
  if (SUPPORTED_LANGS.includes(browserLang)) return browserLang;

  return DEFAULT_LANG;
}

/** Persists the user's default language for future visits. */
export function saveLang(lang) {
  if (SUPPORTED_LANGS.includes(lang)) localStorage.setItem(STORAGE_KEY, lang);
}

/** Sets <html lang/dir> — Hebrew is RTL, and this is the one line that
 * makes the rest of the page (status bar, join gate) lay out correctly
 * without per-element RTL-specific CSS, via the browser's own
 * direction-aware defaults (text-align: start, flexbox's row reversal). */
export function applyLangToDocument(lang) {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
}

export function t(lang, key, ...args) {
  const entry = (translations[lang] ?? translations[DEFAULT_LANG])[key] ?? translations[DEFAULT_LANG][key];
  return typeof entry === "function" ? entry(...args) : entry;
}

export { SUPPORTED_LANGS };
