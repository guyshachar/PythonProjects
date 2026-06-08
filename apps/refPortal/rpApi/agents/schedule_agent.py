"""
Schedule Agent — multi-turn conversational agent for referee schedule queries,
commute planning, and game history analytics.

Conversation steps for commute planning:
  1. User sends a commute/schedule trigger keyword
  2. Agent fetches next game, asks "Where are you coming from?"
  3. User replies with "from home", a free-text address, or a GPS location pin
  4. Agent asks "How many minutes early do you want to arrive?"
  5. Agent calculates departure time + Waze link and replies

Game history queries are answered in a single turn (no multi-step state needed).
"""

import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List, Tuple

import shared.helpers as helpers
from shared.bedrockClient import BedrockClient
from shared.db import CacheService
from shared.logger import Logger

from shared.commute_service import CommuteService


# ---------------------------------------------------------------------------
# Channel constants
# ---------------------------------------------------------------------------

CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_TELEGRAM = "telegram"
CHANNEL_PUSH = "push"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    step: str = "idle"                          # idle | asking_departure | asking_buffer
    next_game: Optional[Dict] = None
    departure_origin: Optional[str] = None
    departure_coords: Optional[Dict] = None     # {lat, lng}
    buffer_minutes: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "AgentState":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ScheduleAgent:
    """Stateful per-user agent that answers schedule questions, plans commute,
    and surfaces game history analytics."""

    _SESSION_TTL = 3600  # 1 hour

    _COMMUTE_TRIGGERS = [
        "נסיעה", "הגעה", "מתי לצאת", "כמה זמן", "שעת יציאה",
        "איך מגיע", "כמה זמן נסיעה",
    ]
    _SCHEDULE_TRIGGERS = [
        "לוח משחקים", "המשחקים שלי", "מתי המשחק", "הבא שלי",
        "יש לי משחק", "איזה משחקים",
    ]
    _HISTORY_TRIGGERS = [
        "היסטוריה", "משחקים שעברו", "כמה משחקים שיחקתי", "כמה משחקים",
        "איזה ליגה", "איזו ליגה", "איזה מגרש", "סטטיסטיקה", "סטטיסטיקות",
        "כמה פעמים", "הכי הרבה", "סיכום",
    ]
    # Past period list queries → same history intent; `_parse_history_time_window` detects listing vs stats.
    _PERIOD_HISTORY_KEYWORDS = [
        "בשבוע האחרון", "השבוע האחרון", "שבוע אחרון", "בשבוע שעבר", "השבוע שעבר",
        "שבוע שעבר", "7 הימים", "שבעה ימים", "שבעת הימים",
        "אתמול", "שבת שעבר", "שבת שעברה", "שבת האחרונה",
        "אילו משחקים היו", "מה המשחקים היו", "איזה משחקים היו", "משחקים שהיו",
        "last week", "last saturday", "yesterday",
    ]
    # Natural-language field queries — the existing keyword handler catches "מגרש X" directly,
    # so these triggers cover phrasing that bypasses it ("כתובת", "איפה", "מיקום", etc.)
    _FIELD_TRIGGERS = [
        "כתובת",
        "פרטי מגרש",
        "פרטים על המגרש",
        "איפה המגרש",
        "איפה מגרש",  # e.g. "איפה מגרש צפרירים" (no definite article)
        "מיקום מגרש",
        "איפה נמצא",
        "טלפון מגרש",
    ]

    # Strip leading boilerplate from field-info questions (fuzzy match runs on the rest).
    _FIELD_QUERY_PREFIXES: Tuple[str, ...] = (
        "מה הכתובת של ",
        "מה הכתובת",
        "מה כתובת של ",
        "מה כתובת",
        "איפה המגרש ",
        "איפה מגרש ",
        "איפה נמצא ",
        "פרטי מגרש ",
        "פרטים על המגרש ",
        "פרטים על מגרש ",
        "מיקום מגרש ",
        "טלפון מגרש ",
        "כתובת של ",
        "כתובת ",
    )

    @staticmethod
    def _normalize_field_match_text(s: str) -> str:
        """Canonical form for fuzzy Hebrew venue matching (common DB vs user typos)."""
        if not s:
            return s
        t = s.lower().strip()
        # "גני תקוה" in chat vs "גני תקווה" in CRM; same for פתח תקווה / נווה / כפר names
        t = t.replace("תקווה", "תקוה")
        return t

    def __init__(
        self,
        logger: Logger,
        cacheService: CacheService,
        bedrockClient: BedrockClient,
        handleRefereeData,
        commuteService: CommuteService,
        llmConfig: Optional[Dict[str, Any]] = None,
    ):
        self.logger = logger
        self.cacheService = cacheService
        self.bedrockClient = bedrockClient
        self.handleRefereeData = handleRefereeData
        self.commuteService = commuteService
        self._llm_config = llmConfig if isinstance(llmConfig, dict) else {}

    def _bedrock_invoke_primary_and_fallbacks(self):
        c = self._llm_config.get('bedrockModelCandidates')
        if not isinstance(c, list) or len(c) == 0:
            mid = self._llm_config.get('bedrockModelId')
            if mid:
                return str(mid).strip(), []
            return None, []
        primary = str(c[0]).strip()
        rest = [str(x).strip() for x in c[1:] if x is not None and str(x).strip()]
        return primary, rest

    def _schedule_agent_bedrock_invoke_params(self) -> tuple:
        """NLU invoke limits from LLM.schedule_agent_* in config (see configurationDI)."""
        cfg = self._llm_config
        max_t = int(cfg.get('schedule_agent_max_tokens', 64))
        temp = float(cfg.get('schedule_agent_temperature', 0.0))
        return max_t, temp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_active_session(self, mobileNo: str) -> bool:
        return self._load_state(mobileNo).step != "idle"

    def should_handle(self, mobileNo: str) -> bool:
        """Always True for known referees — Claude classifies the intent and returns None
        for unrelated messages so they fall through to the next handler."""
        return True

    async def process(
        self,
        mobileNo: str,
        message: str,
        refereeDetail: Dict,
        tenantKey: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        channel: str = CHANNEL_WHATSAPP,
    ) -> Optional[str]:
        state = self._load_state(mobileNo)

        if state.step == "idle":
            reply = await self._handle_idle(mobileNo, message, refereeDetail, tenantKey, state)
        elif state.step == "asking_departure":
            reply = await self._handle_departure(
                mobileNo, message, refereeDetail, state,
                latitude=latitude, longitude=longitude,
            )
        elif state.step == "asking_buffer":
            reply = await self._handle_buffer(mobileNo, message, state)
        else:
            reply = None

        return self._format_for_channel(reply, channel) if reply else None

    # ------------------------------------------------------------------
    # Step handlers
    # ------------------------------------------------------------------

    async def _handle_idle(self, mobileNo, message, refereeDetail, tenantKey, state):
        intent = await self._classify_intent(message)

        if intent == "schedule":
            return self._reply_schedule(mobileNo, refereeDetail, tenantKey)

        if intent == "history":
            window = self._parse_history_time_window(message)
            if window:
                return self._reply_history_games_in_period(
                    mobileNo, refereeDetail, tenantKey, window[0], window[1], window[2]
                )
            return self._reply_history(mobileNo, refereeDetail, tenantKey)

        if intent == "field_info":
            return await self._reply_field_info(message, refereeDetail, tenantKey)

        if intent in ("next_game", "commute"):
            next_game = self._fetch_next_game(mobileNo, refereeDetail, tenantKey)
            if not next_game:
                return "לא נמצאו משחקים קרובים"

            state.next_game = next_game
            game_summary = self._format_game_summary(next_game)

            if intent == "next_game":
                self._clear_state(mobileNo)
                return game_summary

            # commute flow — ask where coming from
            state.step = "asking_departure"
            self._save_state(mobileNo, state)
            return (
                f"{game_summary}\n\n"
                "מאיפה תגיע למשחק?\n"
                "ענה *מהבית* לשימוש בכתובת הבית שלך, שלח כתובת, או שתף מיקום."
            )

        return None

    async def _handle_departure(self, mobileNo, message, refereeDetail, state,
                                 latitude=None, longitude=None):
        if latitude and longitude:
            state.departure_coords = {"lat": latitude, "lng": longitude}
            state.departure_origin = f"{latitude},{longitude}"
        elif any(kw in message for kw in ["מהבית", "הבית", "מביתי", "מהכתובת שלי"]):
            home = refereeDetail.get("address") or refereeDetail.get("homeAddress")
            if not home:
                return (
                    "לא נמצאה כתובת בית בפרופיל שלך.\n"
                    "שלח את הכתובת ממנה תגיע, או שתף מיקום."
                )
            state.departure_origin = home
            state.departure_coords = None
        else:
            state.departure_origin = message.strip()
            state.departure_coords = None

        state.step = "asking_buffer"
        self._save_state(mobileNo, state)
        return "כמה דקות לפני תחילת המשחק תרצה להגיע? (למשל: 15, 20, 30)"

    async def _handle_buffer(self, mobileNo, message, state):
        buffer = self._parse_minutes(message)
        if buffer is None:
            return "לא הבנתי. ענה במספר דקות, למשל: 20"

        state.buffer_minutes = buffer
        reply = await self._build_commute_reply(state)
        self._clear_state(mobileNo)
        return reply

    # ------------------------------------------------------------------
    # Commute calculation
    # ------------------------------------------------------------------

    async def _build_commute_reply(self, state: AgentState) -> str:
        game = state.next_game
        travel_minutes = await self.commuteService.get_travel_minutes(
            origin=state.departure_origin,
            origin_coords=state.departure_coords,
            destination_coords=game.get("fieldCoords"),
            destination_address=game.get("fieldAddress"),
        )

        date_str = game.get("date", "")
        try:
            game_dt = datetime.fromisoformat(date_str)
            buffer = state.buffer_minutes
            departure_dt = game_dt - timedelta(minutes=buffer + travel_minutes)
            departure_time = departure_dt.strftime("%H:%M")
            arrival_time = (game_dt - timedelta(minutes=buffer)).strftime("%H:%M")
            game_date = game_dt.strftime("%d/%m/%Y")
        except Exception:
            return (
                f"זמן נסיעה משוער: {travel_minutes} דקות.\n"
                f"צא {travel_minutes + state.buffer_minutes} דקות לפני תחילת המשחק."
            )

        accuracy_note = "" if self.commuteService.has_live_data else " (הערכה בלבד)"
        lines = [
            f"*תכנון הגעה — {game_date}*",
            f"מגרש: {game.get('field', '')}",
            f"זמן נסיעה משוער: {travel_minutes} דקות{accuracy_note}",
            f"הגעה {state.buffer_minutes} דקות לפני — בשעה {arrival_time}",
            f"*יש לצאת בשעה {departure_time}* 🚗",
        ]

        waze = game.get("fieldWazeLink")
        if waze:
            lines.append(f"\nנווט ב-Waze: {waze}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Schedule reply
    # ------------------------------------------------------------------

    def _reply_schedule(self, mobileNo, refereeDetail, tenantKey) -> str:
        games = self._fetch_upcoming_games(mobileNo, refereeDetail, tenantKey)
        if not games:
            return "לא נמצאו משחקים קרובים"

        lines = ["*המשחקים הקרובים שלך:*"]
        for g in games[:5]:
            gd = g.get("gameDetail", {})
            date_part = gd.get("dateText", "")#g.get("date", "")[:10]
            lines.append(f"• {date_part}  {gd.get('gameTitle', '')} {gd.get('tournamentName', '')} ({gd.get('field', '')})")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # History analytics
    # ------------------------------------------------------------------

    def _reply_history(self, mobileNo, refereeDetail, tenantKey) -> str:
        games_dict = self._fetch_all_games(mobileNo, refereeDetail, tenantKey)
        if not games_dict:
            return "לא נמצאו משחקים בהיסטוריה שלך"

        games = list(games_dict.values())
        total = len(games)

        # Top tournaments
        tournament_counts = Counter(
            g.get("tournamentName", "לא ידוע") for g in games if g.get("tournamentName")
        )
        top_tournaments = tournament_counts.most_common(3)

        # Top fields
        field_counts = Counter(
            g.get("field", "לא ידוע") for g in games if g.get("field")
        )
        top_fields = field_counts.most_common(3)

        # Role breakdown — find the referee's role in each game by matching on name
        ref_name = (refereeDetail.get("name") or "").strip()
        role_counts = Counter()
        for g in games:
            for ref_entry in (g.get("referees") or []):
                entry_name = (ref_entry.get("* name") or "").strip()
                if ref_name and ref_name in entry_name:
                    role = ref_entry.get("role", "לא ידוע")
                    role_counts[role] += 1
                    break

        # Date range
        dates = sorted(
            g.get("date", "")[:10] for g in games if g.get("date")
        )
        date_range = f"{dates[0]} עד {dates[-1]}" if dates else "לא ידוע"

        lines = [
            f"*היסטוריית המשחקים שלך*",
            f"סה\"כ משחקים: {total}  ({date_range})",
            "",
            "*ליגות / טורנירים מובילים:*",
        ]
        for name, count in top_tournaments:
            lines.append(f"• {name}: {count} משחקים")

        lines += ["", "*מגרשים מובילים:*"]
        for name, count in top_fields:
            lines.append(f"• {name}: {count} משחקים")

        if role_counts:
            lines += ["", "*תפקידים:*"]
            for role, count in role_counts.most_common():
                lines.append(f"• {role}: {count} משחקים")

        return "\n".join(lines)

    def _reply_history_games_in_period(
        self,
        mobileNo,
        refereeDetail,
        tenantKey,
        from_dt: datetime,
        to_dt: datetime,
        period_label: str,
    ) -> str:
        """List games that already occurred in [from_dt, to_dt] (local time)."""
        keys = refereeDetail.get("activeTenantKeys", [tenantKey])
        games = self.handleRefereeData.getRefereeGames(
            tenantKey=keys,
            mobileNo=mobileNo,
            includeArchived=True,
            includeCanceled=False,
            from_date=from_dt,
            to_date=to_dt,
        )
        if not games:
            return f"לא נמצאו משחקים {period_label}."

        self.handleRefereeData.enrichRefereeItems(games)
        now = helpers.localNow()
        filtered: List[Dict] = []
        for g in games.values():
            gdt = self._game_datetime_value(g)
            if gdt is None:
                continue
            if gdt < from_dt or gdt > to_dt:
                continue
            if gdt > now:
                continue
            filtered.append(g)

        filtered.sort(key=lambda x: self._game_datetime_value(x) or datetime.min, reverse=False)

        if not filtered:
            return f"לא נמצאו משחקים {period_label}."

        lines = [f"*המשחקים שלך {period_label}:*"]
        for g in filtered[:20]:
            gd = g.get("gameDetail") or {}
            date_part = gd.get("dateText", "") or str(g.get("date", ""))[:16]
            lines.append(
                f"• {date_part}  {gd.get('gameTitle', '')} {gd.get('tournamentName', '')} ({gd.get('field', '')})"
            )
        if len(filtered) > 20:
            lines.append(f"… ועוד {len(filtered) - 20} משחקים")
        return "\n".join(lines)

    def _game_datetime_value(self, g: Dict) -> Optional[datetime]:
        raw = g.get("date")
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw
        s = str(raw).strip()
        if not s:
            return None
        try:
            if "T" in s or len(s) > 10:
                return datetime.fromisoformat(s.replace("Z", "").split("+")[0])
            return datetime.fromisoformat(s[:10])
        except (TypeError, ValueError):
            return None

    def _week_start_sunday(self, d: date) -> date:
        """Week starts Sunday (IL). Python: Monday=0 … Sunday=6."""
        return d - timedelta(days=(d.weekday() - 6) % 7)

    def _last_occurrence_weekday(self, today: date, target_weekday: int) -> date:
        """Latest date <= today with given weekday, excluding today if today matches (previous occurrence)."""
        delta = (today.weekday() - target_weekday) % 7
        if delta == 0:
            delta = 7
        return today - timedelta(days=delta)

    def _day_range(self, d: date) -> Tuple[datetime, datetime]:
        start = datetime.combine(d, datetime.min.time())
        end = datetime.combine(d, datetime.max.time())
        return start, end

    def _parse_history_time_window(self, message: str) -> Optional[Tuple[datetime, datetime, str]]:
        """
        If the user asks for games in a concrete past window, return
        (from_dt, to_dt, Hebrew label for reply). Otherwise None → aggregate stats.
        """
        tl = message.strip().lower()
        today = helpers.localNow().date()

        # --- English ---
        if "yesterday" in tl:
            d = today - timedelta(days=1)
            a, b = self._day_range(d)
            return a, b, "אתמול"
        if "last saturday" in tl:
            d = self._last_occurrence_weekday(today, target_weekday=5)
            a, b = self._day_range(d)
            return a, b, "בשבת שעברה"
        if "last week" in tl:
            sun = self._week_start_sunday(today)
            prev_start = sun - timedelta(days=7)
            prev_end = sun - timedelta(days=1)
            a, b = self._day_range(prev_start)
            _, b2 = self._day_range(prev_end)
            return a, b2, "בשבוע שעבר"

        # --- Hebrew weeks (שבוע שעבר = previous Sun–Sat; …האחרון = rolling 7 days) ---
        if any(p in message for p in ("בשבוע שעבר", "השבוע שעבר", "שבוע שעבר")):
            sun = self._week_start_sunday(today)
            prev_start = sun - timedelta(days=7)
            prev_end = sun - timedelta(days=1)
            a, _ = self._day_range(prev_start)
            _, b = self._day_range(prev_end)
            return a, b, "בשבוע שעבר"

        if any(p in message for p in ("בשבוע האחרון", "השבוע האחרון", "שבוע אחרון")):
            start_d = today - timedelta(days=6)
            a, _ = self._day_range(start_d)
            _, b = self._day_range(today)
            return a, b, "בשבוע האחרון"

        if "אתמול" in message:
            d = today - timedelta(days=1)
            a, b = self._day_range(d)
            return a, b, "אתמול"

        # Rolling 7 days
        if any(p in message for p in ("7 הימים", "שבעה ימים", "שבעת הימים")):
            start_d = today - timedelta(days=6)
            a, _ = self._day_range(start_d)
            _, b = self._day_range(today)
            return a, b, "בשבעת הימים האחרונים"

        # Hebrew weekdays "ביום X שעבר" / "X שעברה"
        _day_specs: List[Tuple[Tuple[str, ...], int, str]] = [
            (("שבת שעבר", "שבת שעברה", "שבת האחרונה", "ביום שבת שעבר"), 5, "בשבת שעברה"),
            (("יום ראשון שעבר", "ראשון שעבר"), 6, "ביום ראשון שעבר"),
            (("יום שני שעבר", "שני שעבר"), 0, "ביום שני שעבר"),
            (("יום שלישי שעבר", "שלישי שעבר"), 1, "ביום שלישי שעבר"),
            (("יום רביעי שעבר", "רביעי שעבר"), 2, "ביום רביעי שעבר"),
            (("יום חמישי שעבר", "חמישי שעבר"), 3, "ביום חמישי שעבר"),
            (("יום שישי שעבר", "שישי שעבר"), 4, "ביום שישי שעבר"),
        ]
        for phrases, wd, label in _day_specs:
            if any(p in message for p in phrases):
                d = self._last_occurrence_weekday(today, target_weekday=wd)
                a, b = self._day_range(d)
                return a, b, label

        # "אילו משחקים … " style without a date → skip (aggregate stats)
        return None

    # ------------------------------------------------------------------
    # Field info
    # ------------------------------------------------------------------

    async def _reply_field_info(self, message: str, refereeDetail: Dict, tenantKey: str) -> str:
        keys = refereeDetail.get("activeTenantKeys", [tenantKey])
        choices = self._merge_fields_choices_for_intuitive_match(keys)

        not_found = (
            "לא מצאתי פרטי מגרש בהודעה שלך.\n"
            "ציין את שם המגרש, למשל: *כתובת אצטדיון X*"
        )
        if not choices:
            return not_found

        query = self._field_query_string_for_match(message)
        field = self._resolve_field_with_intuitive_match(query, choices)
        if not field:
            return not_found

        return self._format_field_details(field)

    def _field_query_string_for_match(self, message: str) -> str:
        t = message.strip().lower()
        for prefix in self._FIELD_QUERY_PREFIXES:
            if t.startswith(prefix):
                t = t[len(prefix) :].strip()
                break
        return t.rstrip("?.!,:;").strip()

    def _resolve_field_with_intuitive_match(
        self, query: str, choices: Dict[str, Dict]
    ) -> Optional[Dict]:
        if not query or not choices:
            return None
        qn = self._normalize_field_match_text(query.strip())
        if len(qn) < 2:
            return None
        m = helpers.find_intuitive_matches(qn, choices, cutoff=0.5)
        if not m:
            return None
        return choices.get(m[0])

    def _merge_fields_choices_for_intuitive_match(
        self, tenant_keys: List[str]
    ) -> Dict[str, Dict]:
        """Like findFieldDetails: dict keys + title + findText for helpers.find_intuitive_matches."""
        choices: Dict[str, Dict] = {}
        for tkey in tenant_keys:
            for fname, field in (self.cacheService.getFields(tenantKey=tkey) or {}).items():
                if not isinstance(field, dict):
                    continue
                choices[fname] = field
                title = (field.get("title") or "").strip().lower()
                if title and title != str(fname).lower() and title not in choices:
                    choices[title] = field
                ft = (field.get("findText") or "").strip().lower()
                if ft and ft not in choices:
                    choices[ft] = field
        return choices

    def _format_field_details(self, field: Dict) -> str:
        lines = [f"*פרטי המגרש: {field.get('title', '')}*"]
        addr = field.get("addressDetails") or {}
        if addr.get("address"):
            lines.append(f"כתובת: {addr['address']}")
        if field.get("level"):
            lines.append(f"רמת מתקן: {field['level']}")
        if field.get("contact"):
            lines.append(f"אחראי: {field['contact']}")
        if field.get("phone"):
            lines.append(f"טלפון: {field['phone']}")
        if addr.get("wazeLink"):
            lines.append(f"Waze: {addr['wazeLink']}")
        coords = addr.get("coordinates") or {}
        if coords.get("lat") and coords.get("lng"):
            lines.append(
                f"מפות: https://www.google.com/maps?q={coords['lat']},{coords['lng']}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_next_game(self, mobileNo, refereeDetail, tenantKey) -> Optional[Dict]:
        games = self._fetch_upcoming_games(mobileNo, refereeDetail, tenantKey)
        if not games:
            return None

        game_ref = games[0]
        full = game_ref.get('gameDetail')
        if not isinstance(full, dict):
            full = dict(game_ref)

        field = self.cacheService.get_field_by_name(
            tenantKey=full.get("tenantKey", tenantKey),
            fieldName=full.get("field"),
        )
        if field:
            addr = field.get("addressDetails") or {}
            full["fieldAddress"] = addr.get("address")
            full["fieldWazeLink"] = addr.get("wazeLink")
            coords = addr.get("coordinates")
            if coords:
                full["fieldCoords"] = {"lat": coords["lat"], "lng": coords["lng"]}

        return full

    def _fetch_upcoming_games(self, mobileNo, refereeDetail, tenantKey) -> List[Dict]:
        keys = refereeDetail.get("activeTenantKeys", [tenantKey])
        now = helpers.localNow()
        games = self.handleRefereeData.getRefereeGames(
            tenantKey=keys, mobileNo=mobileNo, from_date=now
        )
        if not games:
            return []
        self.handleRefereeData.enrichRefereeItems(games)
        return sorted(games.values(), key=lambda g: g.get("date", ""))

    def _fetch_all_games(self, mobileNo, refereeDetail, tenantKey) -> Dict:
        keys = refereeDetail.get("activeTenantKeys", [tenantKey])
        games = self.handleRefereeData.getRefereeGames(
            tenantKey=keys,
            mobileNo=mobileNo,
            includeArchived=True,
            includeCanceled=False,
        )
        self.handleRefereeData.enrichRefereeItems(games)
        return games

    def _reconcile_schedule_vs_history_for_past_window(self, message: str, label: str) -> str:
        """
        The model often returns *schedule* for past-period questions such as
        "מה שפטתי בשבוע האחרון" (overlap with "list my games").
        If we recognize a concrete past time window, prefer *history* unless the
        message clearly asks for future/upcoming games.
        """
        if label != "schedule":
            return label
        if self._parse_history_time_window(message) is None:
            return label

        future_markers = (
            "הבא", "הקרוב", "קרובים", "המתקרב", "עתיד", "צפוי",
        )
        if any(m in message for m in future_markers):
            if not any(p in message for p in ("שבוע שעבר", "שבת שעבר", "אתמול", "שפט")):
                return label

        past_markers = (
            "שפט", "שיפט", "שיחקתי", "היו לי", "היה לי", "ניצח", "הפסד",
            "משחקים שעבר", "משחקים שהיו",
        )
        if any(m in message for m in past_markers):
            return "history"

        if any(
            p in message
            for p in (
                "שבוע האחרון",
                "שבוע שעבר",
                "השבוע שעבר",
                "בשבוע האחרון",
                "אתמול",
                "שבת שעבר",
                "שבת שעברה",
                "שבת האחרונה",
                "7 הימים",
                "שבעה ימים",
            )
        ):
            return "history"

        return label

    def _reconcile_field_info_vs_misclassified_schedule(self, message: str, label: str) -> str:
        """
        The model often returns *schedule* when the user asks for a venue address
        (e.g. "מה הכתובת של מגרש צפרירים") because of the word "משחקים" patterns
        or loose association with games. Prefer *field_info* when field triggers match.
        """
        if label not in ("schedule", "next_game", "commute", "other"):
            return label
        if any(kw in message for kw in self._FIELD_TRIGGERS):
            return "field_info"
        return label

    # ------------------------------------------------------------------
    # NLU — intent classification via Claude
    # ------------------------------------------------------------------

    async def _classify_intent(self, message: str) -> str:
        # Deterministic path first: field triggers were only used as fallback after LLM,
        # but the model often mislabels address/location questions as schedule.
        if any(kw in message for kw in self._FIELD_TRIGGERS):
            return "field_info"

        prompt = (
            "Classify this Hebrew message from a sports referee into exactly one label:\n"
            "  schedule   — asking for the list of **upcoming** games only\n"
            "  next_game  — asking about the details of their **next** game only\n"
            "  commute    — asking about travel time, when to leave, or how to reach a game venue\n"
            "  history    — **past** games already played (e.g. שפטתי / אילו משחקים היו) "
            "in a time range (שבוע האחרון, אתמול, שבת שעבר), OR statistics / counts\n"
            "  field_info — asking for address, location, contact, or any details about a **named** "
            "field/stadium (e.g. כתובת/איפה מגרש X), NOT a general game list\n"
            "  other      — anything else\n\n"
            "Examples: \"מה שפטתי בשבוע האחרון\" → history. "
            "\"לוח המשחקים / המשחקים הקרובים\" → schedule. "
            "\"מה הכתובת של מגרש צפרירים\" / \"איפה מגרש צפרירים\" → field_info.\n\n"
            f'Message: "{message}"\n\n'
            "Reply with only the single word label."
        )
        try:
            primary, fallbacks = self._bedrock_invoke_primary_and_fallbacks()
            if not primary:
                return "other"
            max_t, temp = self._schedule_agent_bedrock_invoke_params()
            resp = self.bedrockClient.invoke_model_async(
                model_id=primary,
                fallback_model_ids=fallbacks,
                prompt=prompt,
                max_tokens=max_t,
                temperature=temp,
            )
            label = (resp.get("text") or "").strip().lower().split()[0]
            if label in ("schedule", "next_game", "commute", "history", "field_info", "other"):
                label = self._reconcile_field_info_vs_misclassified_schedule(message, label)
                return self._reconcile_schedule_vs_history_for_past_window(message, label)
        except Exception as e:
            self.logger.warning("Intent classification failed:", e)

        # keyword fallback
        if any(kw in message for kw in self._FIELD_TRIGGERS):
            return "field_info"
        if any(kw in message for kw in self._PERIOD_HISTORY_KEYWORDS) or any(
            kw in message for kw in self._HISTORY_TRIGGERS
        ):
            return "history"
        if any(kw in message for kw in self._COMMUTE_TRIGGERS):
            return "commute"
        if any(kw in message for kw in self._SCHEDULE_TRIGGERS):
            return self._reconcile_schedule_vs_history_for_past_window(message, "schedule")
        return "other"

    # ------------------------------------------------------------------
    # Multi-channel formatting
    # ------------------------------------------------------------------

    def _format_for_channel(self, text: str, channel: str) -> str:
        if channel == CHANNEL_PUSH:
            # Strip WhatsApp/Telegram markdown for plain-text push payloads
            text = re.sub(r"\*(.+?)\*", r"\1", text)
        return text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_game_summary(self, game: Dict) -> str:
        lines = ["*המשחק הבא שלך:*"]
        date_str = game.get("date", "")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                lines.append(f"תאריך: {dt.strftime('%d/%m/%Y')} בשעה {dt.strftime('%H:%M')}")
            except Exception:
                lines.append(f"תאריך: {date_str}")
        if game.get("tournamentName"):
            lines.append(f"מסגרת: {game['tournamentName']}")
        if game.get("gameTitle"):
            lines.append(f"משחק: {game['gameTitle']}")
        if game.get("field"):
            lines.append(f"מגרש: {game['field']}")
        if game.get("fieldAddress"):
            lines.append(f"כתובת: {game['fieldAddress']}")
        return "\n".join(lines)

    _HEBREW_MINUTES = {
        "רבע שעה": 15, "רבע": 15,
        "חצי שעה": 30, "חצי": 30,
        "שעה": 60,
    }

    def _parse_minutes(self, text: str) -> Optional[int]:
        for phrase, mins in self._HEBREW_MINUTES.items():
            if phrase in text:
                return mins
        m = re.search(r"(\d+)", text)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 120:
                return val
        return None

    # ------------------------------------------------------------------
    # State management (Redis with TTL)
    # ------------------------------------------------------------------

    def _state_key(self, mobileNo: str) -> str:
        return f"agent:schedule:{mobileNo}"

    def _load_state(self, mobileNo: str) -> AgentState:
        try:
            raw = self.cacheService._redis_get(self._state_key(mobileNo))
            if raw:
                return AgentState.from_dict(raw)
        except Exception as e:
            self.logger.warning(f"Could not load agent state for {mobileNo}:", e)
        return AgentState()

    def _save_state(self, mobileNo: str, state: AgentState):
        try:
            self.cacheService._redis_set(
                key=self._state_key(mobileNo),
                data=state.to_dict(),
                ttl_seconds=self._SESSION_TTL,
            )
        except Exception as e:
            self.logger.warning(f"Could not save agent state for {mobileNo}:", e)

    def _clear_state(self, mobileNo: str):
        try:
            self.cacheService.redisCacheClient.delete(self._state_key(mobileNo))
        except Exception as e:
            self.logger.warning(f"Could not clear agent state for {mobileNo}:", e)
