#!/usr/bin/env python3.12
"""
LLM Webhook Integration for Referee Portal

This module integrates an LLM with your existing webhook system to provide
intelligent responses based on your documentation and data.

Features:
- Document-based knowledge base
- Context-aware responses
- Integration with existing webhook flow
- Multi-language support (Hebrew/English)
- Field and referee data integration
"""

import os
import sys
import json
import asyncio
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests
from dataclasses import dataclass

# PDF processing imports
try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("⚠️  ReportLab not available. Install with: pip install reportlab")

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    print("⚠️  pdfplumber not available. Install with: pip install pdfplumber")

# Add shared modules to path
sys.path.append(str(Path(__file__).resolve().parent))
from shared.bedrockClient import BedrockClient
from shared.logger import Logger
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db import CacheService

@dataclass
class LLMResponse:
    """Structured response from LLM"""
    answer: str
    confidence: float
    sources: List[str]
    action_required: bool
    action_type: Optional[str] = None
    action_data: Optional[Dict] = None

class LLMWebhookIntegration:
    """LLM integration for webhook responses"""
    
    def __init__(self, 
                 logger: Logger,
                 bedrock_client: BedrockClient,
                 cacheService: CacheService,
                 docs_service_url: str,
                 config: Dict[str, Any],
                 handle_referee_data: Any = None):
        
        self.logger = logger
        self.bedrock_client = bedrock_client
        self.cacheService = cacheService
        self.handle_referee_data = handle_referee_data
        self.docs_service_url = docs_service_url
        self.config = config
        self.llmConfig = config.get('LLM') if isinstance(config.get('LLM'), dict) else {}
        
        # Initialize knowledge base
        self.knowledge_base = {}
        self.intent_phrases = {}
        self.fields_data = {}
        self.referee_data = {}
        
        self.generateFieldsDetails()

        # Load all documentation and data
        asyncio.create_task(self.load_knowledge_base())
        
        # Try different models in order of preference (from LLM.bedrockModelCandidates in config).
        raw_ids = self.llmConfig.get('bedrockModelCandidates') if isinstance(self.llmConfig, dict) else None
        self.model_ids = list(raw_ids) if isinstance(raw_ids, list) and len(raw_ids) > 0 else []
        if not self.model_ids and isinstance(self.llmConfig, dict) and self.llmConfig.get('bedrockModelId'):
            self.model_ids = [str(self.llmConfig.get('bedrockModelId')).strip()]
        self.model_id = self.model_ids[0] if self.model_ids else ''
        self.max_tokens = self.llmConfig.get('max_tokens', 4000) if isinstance(self.llmConfig, dict) else 4000
        self.temperature = self.llmConfig.get('temperature', 0.3) if isinstance(self.llmConfig, dict) else 0.3
        
        self.logger.info("LLM Webhook Integration initialized")
    
    def extract_text_from_pdf(self, pdf_url: str) -> str:
        """Extract text from PDF file"""
        try:
            # Download PDF file
            response = requests.get(pdf_url, timeout=30)
            response.raise_for_status()
            
            # Save to temporary file
            temp_pdf_path = f"/tmp/temp_pdf_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            with open(temp_pdf_path, 'wb') as f:
                f.write(response.content)
            
            text_content = ""
            
            # Try pdfplumber first (better for complex layouts)
            if PDFPLUMBER_AVAILABLE:
                try:
                    with pdfplumber.open(temp_pdf_path) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text_content += page_text + "\n"
                    self.logger.info(f"Successfully extracted text from PDF using pdfplumber")
                except Exception as e:
                    self.logger.warning(f"pdfplumber failed:", e)
            
            # ReportLab fallback - basic PDF reading capability
            if not text_content and PDF_AVAILABLE:
                try:
                    # ReportLab is primarily for PDF creation, not text extraction
                    # We'll rely on pdfplumber for text extraction
                    self.logger.info("ReportLab available but limited text extraction capability")
                except Exception as e:
                    self.logger.error(f"ReportLab fallback failed:", e)
            
            # Clean up temporary file
            try:
                os.remove(temp_pdf_path)
            except:
                pass
            
            if text_content:
                return text_content.strip()
            else:
                return f"Could not extract text from PDF: {pdf_url}"
                
        except Exception as e:
            self.logger.error(f"Error extracting text from PDF {pdf_url}:", e)
            return f"Error processing PDF: {str(e)}"
    
    async def load_knowledge_base(self):
        """Load all documentation and data into knowledge base"""
        try:
            # Load intent phrases
            self.load_intent_phrases()
            
            # Load documentation files
            self.load_documentation_files()
            
            # Load fields data
            self.load_fields_data()
            
            # Load referee data
            self.load_referee_data()
            
            self.logger.info(f"Knowledge base loaded: {len(self.knowledge_base)} documents")
            
        except Exception as e:
            self.logger.error(f"Error loading knowledge base:", e)
    
    def load_intent_phrases(self):
        """Load intent phrases from config"""
        '''
        try:
            url = f'{self.docs_service_url}config/intentPhrases.json'
            response = requests.get(url)
            self.intent_phrases = response.json()
            self.logger.info(f"Loaded {len(self.intent_phrases)} intent phrases")
        except Exception as e:
            self.logger.error(f"Error loading intent phrases:", e)
        '''
        url = f'{self.docs_service_url}config/intentPhrases2.json'
        response = requests.get(url)
        self.intent_phrases = response.json()

        for value in self.intent_phrases.values():
            if value.get('type') == 'file' and value.get('file').endswith('.txt'):
                url = f'{self.docs_service_url}{value.get("file")}'
                response = requests.get(url)
                value["content"] = response.text
            elif value.get('type') == 'function':
                function = getattr(self, value.get('function'))
                value["content"] = function()

    def getFieldsDetails(self):
        return self.fieldsDetails

    def generateFieldsDetails(self):
        fields = self.cacheService.getFields()
        self.fieldsDetails = {
            key: {"field": field, "variants": list(field.values()), "findText": key + ' '.join(helpers.flatten_values(field)), "details": self.generateFieldDetails(field)}
            for key, field in fields.items()
        }
        return self.fieldsDetails

    def generateFieldDetails(self, field):
        fieldDetails = f'*פרטי המגרש:*'
        fieldDetails += f' {field.get('title')}'
        fieldAddressDetails = field.get('addressDetails') 
        fieldLocation = None
        #'latitude': to_coordinates_lat, 'longitude': to_coordinates_lng, 'name': field['title'], 'address': fieldAddressDetails['address']})
        if fieldAddressDetails:
            fieldDetails += f'\nכתובת: {fieldAddressDetails.get('address')}'
            to_coordinates_lat = fieldAddressDetails['coordinates']['lat']
            to_coordinates_lng = fieldAddressDetails['coordinates']['lng']
            fieldLocation = {
                "latitude": to_coordinates_lat,
                "longitude": to_coordinates_lng,
                "name": field.get('title'),
                "address": fieldAddressDetails.get('address')
            }
            #fieldDetails += f'\nhttps://www.google.com/maps?q={to_coordinates_lat},{to_coordinates_lng}'
            if field.get('level'):
                fieldDetails += f'\nרמת מתקן: {field['level']}'
            if field.get('contact'):
                fieldDetails += f'\nאחראי: {field['contact']}'
            if field.get('phone'):
                fieldDetails += f'\nטלפון: {field['phone']}'
            fieldDetails += f'\n{fieldAddressDetails["wazeLink"]}'
        
        return { "reply": fieldDetails, "location": fieldLocation }
    
    def load_documentation_files(self):
        """Load documentation files from S3/docs service"""
        try:
            # Load documentation files mentioned in intent phrases
            for key, value in self.intent_phrases.items():
                if value.get('type') == 'file' and (value['file'].endswith('.txt') or value['file'].endswith('.pdf')):
                    try:
                        url = f'{self.docs_service_url}{value["file"]}'
                        
                        if value['file'].endswith('.pdf'):
                            # Extract text from PDF
                            if PDF_AVAILABLE or PDFPLUMBER_AVAILABLE:
                                pdf_text = self.extract_text_from_pdf(url)
                                if pdf_text and not pdf_text.startswith("Error") and not pdf_text.startswith("Could not"):
                                    self.knowledge_base[key] = pdf_text
                                    self.logger.info(f"Loaded PDF documentation: {key} ({len(pdf_text)} characters)")
                                else:
                                    self.logger.warning(f"Could not extract text from PDF {key}: {pdf_text}")
                            else:
                                self.logger.warning(f"PDF processing libraries not available. Install reportlab or pdfplumber")
                        else:
                            # Load text file
                            response = requests.get(url)
                            if response.status_code == 200:
                                self.knowledge_base[key] = response.text
                                self.logger.info(f"Loaded text documentation: {key}")
                            else:
                                self.logger.warning(f"Could not load {key}: HTTP {response.status_code}")
                    except Exception as e:
                        self.logger.warning(f"Could not load {key}:", e)
            
        except Exception as e:
            self.logger.error(f"Error loading documentation files:", e)
    
    def load_fields_data(self):
        """Load fields data from database"""
        try:
            self.fields_data = self.intent_phrases['fields']
            self.logger.info(f"Loaded {len(self.fields_data.get('content'))} fields")
        except Exception as e:
            self.logger.error(f"Error loading fields data:", e)
    
    def load_referee_data(self):
        """Load referee data from database"""
        try:
            # This would need to be adapted based on your referee data structure
            self.referee_data = {}
            self.logger.info("Referee data loaded")
        except Exception as e:
            self.logger.error(f"Error loading referee data:", e)
    
    def _wants_personal_assignment_facts(self, message: str) -> bool:
        m = message.lower().strip()
        if not m:
            return False
        if not self.handle_referee_data:
            return False
        if (
            any(x in m for x in ('כתובת', 'איך מגיעים', 'מגיעים', 'ניווט', 'וייז', 'waze'))
            and 'מגרש' in m
            and not any(
                x in m
                for x in (
                    'יש לי',
                    'שלי',
                    'שפטתי',
                    'שיפטתי',
                    'בקרוב',
                    'שבוע שעבר',
                    'שנתון',
                    'קבוצה',
                    'בדרך כלל',
                    'הכי הרבה',
                )
            )
        ):
            return False
        triggers = (
            'יש לי',
            'שלי',
            'שפטתי',
            'שיפטתי',
            'בקרוב',
            'עתיד',
            'הבאים',
            'המשחק הבא',
            'שבוע שעבר',
            'בשבוע שעבר',
            'בימי שבת',
            'יום שבת',
            'בשבת',
            'בדרך כלל',
            'הכי הרבה',
            'מי הקבוצה',
            'איזה קבוצה',
            'קבוצה ש',
            'שנתון',
            'איזה שנתון',
            'אילו משחקים',
            'איזה משחקים',
            'משחקים יש ל',
            'מתי משחק',
        )
        return any(t in m for t in triggers)

    def _start_of_week_sunday_date(self, d):
        """Sunday (inclusive) start of calendar week Sun–Sat; accepts date or datetime."""
        if isinstance(d, datetime):
            dd = d.date()
        else:
            dd = d
        offset = (dd.weekday() + 1) % 7
        return dd - timedelta(days=offset)

    def _last_completed_sun_sat_bounds(self, now: datetime):
        """Previous full Sun–Sat week, local naive time. Returns (start_dt inclusive, end_dt exclusive)."""
        d = now.date()
        this_week_sun = self._start_of_week_sunday_date(d)
        last_week_sun = this_week_sun - timedelta(days=7)
        last_week_end_excl = this_week_sun
        start_dt = datetime.combine(last_week_sun, datetime.min.time())
        end_dt = datetime.combine(last_week_end_excl, datetime.min.time())
        return start_dt, end_dt

    def _parse_game_datetime(self, merged: dict) -> Optional[datetime]:
        raw = merged.get('date')
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw.replace(tzinfo=None) if raw.tzinfo else raw
        if isinstance(raw, str):
            try:
                if 'T' in raw:
                    return datetime.fromisoformat(raw.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                pass
            try:
                return helpers.convert_to_datetime(raw)
            except Exception:
                return None
        return None

    def _merge_game_row(self, game_row: dict) -> dict:
        gd = {}
        try:
            tnk = game_row.get('tenantKey')
            if tnk:
                gd = self.cacheService.getGameDetail(tenantKey=tnk, game=game_row) or {}
        except Exception as ex:
            self.logger.warning('LLM merge_game_row', ex)
        out = {**game_row}
        for k, v in gd.items():
            if v is not None:
                out[k] = v
        return out

    def _format_game_line(self, merged: dict, idx: int) -> str:
        dt = self._parse_game_datetime(merged)
        dt_s = dt.strftime('%Y-%m-%d %H:%M') if dt else '?'
        tn = merged.get('tournamentName') or ''
        title = merged.get('gameTitle') or ''
        field = merged.get('field') or ''
        role = merged.get('role') or ''
        return f'{idx}. {dt_s} | {tn} | {title} | מגרש: {field} | תפקיד: {role}'

    def _teams_from_title(self, title: str) -> List[str]:
        if not title:
            return []
        parts = re.split(r'\s*[-–—]\s*', title, maxsplit=1)
        teams = []
        for p in parts:
            t = (p or '').strip()
            if len(t) > 1:
                teams.append(t)
        return teams

    def _build_personal_assignment_context(self, message: str, referee_detail: dict) -> str:
        if not self.handle_referee_data or not referee_detail:
            return ''
        mobile = referee_detail.get('mobileNo')
        tenant_keys = referee_detail.get('activeTenantKeys') or []
        if not mobile or not tenant_keys:
            return ''
        m = message.lower()
        now = helpers.localNow()
        h = self.handle_referee_data

        want_upcoming = any(
            x in m
            for x in (
                'בקרוב',
                'עתיד',
                'הבא',
                'הבאה',
                'הבאים',
                'המשחק הבא',
                'יש לי',
                'אילו משחק',
                'איזה משחק',
                'מתי ',
            )
        )
        want_last_week = 'שבוע שעבר' in m or 'בשבוע שעבר' in m
        want_sat_stat = ('שבת' in m or 'בשבת' in m or 'בימי שבת' in m) and any(
            x in m for x in ('שנתון', 'ליגה', 'באיזה', 'איזה', 'בדרך כלל', 'רוב', 'בעיקר')
        )
        want_top_team = any(
            x in m for x in ('הכי הרבה', 'מי הקבוצה', 'איזה קבוצה', 'קבוצה ששפט', 'ביותר משחקים')
        )

        generic_personal_schedule = (
            not want_last_week
            and not want_sat_stat
            and not want_top_team
            and ('משחק' in m or 'שיבוצ' in m)
            and any(x in m for x in ('יש לי', 'שלי', 'אני '))
        )
        if not (want_upcoming or want_last_week or want_sat_stat or want_top_team or generic_personal_schedule):
            return ''

        lines: List[str] = [
            '--- נתוני שיבוצים אישיים (מסד נתוני האפליקציה; ענה/י על שאלות לו״ז וסטטיסטיקה של השופט רק לפי הקטעים שלהלן ואל תמציא/י משחקים) ---'
        ]

        max_lines = 35
        if isinstance(self.llmConfig, dict) and self.llmConfig.get('personal_games_max_lines'):
            try:
                max_lines = int(self.llmConfig.get('personal_games_max_lines'))
            except (TypeError, ValueError):
                max_lines = 35

        if want_upcoming or generic_personal_schedule:
            g = h.getRefereeGames(
                tenantKey=tenant_keys,
                mobileNo=mobile,
                includeArchived=True,
                includeRemoved=False,
                includeCanceled=False,
                from_date=now,
                to_date=now + timedelta(days=120),
            )
            merged_list = []
            for row in g.values():
                merged = self._merge_game_row(row)
                dt = self._parse_game_datetime(merged)
                if dt and dt >= now - timedelta(minutes=2):
                    merged_list.append((dt, merged))
            merged_list.sort(key=lambda x: x[0])
            lines.append('משחקים קרובים (זמן מקומי):')
            if not merged_list:
                lines.append('(אין משחקים מתוכננים בטווח שנמשך)')
            for i, (_, mg) in enumerate(merged_list[:max_lines], start=1):
                lines.append(self._format_game_line(mg, i))
            if len(merged_list) > max_lines:
                lines.append(f'... ועוד {len(merged_list) - max_lines} משחקים שלא הוצגו')

        if want_last_week:
            start_dt, end_dt = self._last_completed_sun_sat_bounds(now)
            g = h.getRefereeGames(
                tenantKey=tenant_keys,
                mobileNo=mobile,
                includeArchived=True,
                includeRemoved=False,
                includeCanceled=True,
                from_date=start_dt,
                to_date=end_dt,
            )
            merged_list = []
            for row in g.values():
                merged = self._merge_game_row(row)
                dt = self._parse_game_datetime(merged)
                if dt and start_dt <= dt < end_dt:
                    merged_list.append((dt, merged))
            merged_list.sort(key=lambda x: x[0])
            end_display = end_dt - timedelta(seconds=1)
            lines.append(
                f'משחקים בשבוע הקלנדרי האחרון שהסתיים (מיום ראשון {start_dt.strftime("%d/%m/%Y")} עד שבת {end_display.strftime("%d/%m/%Y")}):'
            )
            if not merged_list:
                lines.append('(לא נמצאו משחקים בטווח זה)')
            for i, (_, mg) in enumerate(merged_list[:max_lines], start=1):
                lines.append(self._format_game_line(mg, i))

        need_hist = want_sat_stat or want_top_team
        hist_games: List[dict] = []
        if need_hist:
            stats_window_start = now - timedelta(days=800)
            g = h.getRefereeGames(
                tenantKey=tenant_keys,
                mobileNo=mobile,
                includeArchived=True,
                includeRemoved=False,
                includeCanceled=True,
                from_date=stats_window_start,
                to_date=now,
            )
            for row in g.values():
                merged = self._merge_game_row(row)
                dt = self._parse_game_datetime(merged)
                if dt and dt < now:
                    hist_games.append(merged)

        if want_sat_stat:
            lines.append('סטטיסטיקת ליגות בימי שבת (משחקים שכבר התקיימו בטווח היסטוריה שנמשך):')
            sat_rows = []
            for mg in hist_games:
                dt = self._parse_game_datetime(mg)
                if dt and dt.weekday() == 5:
                    sat_rows.append(mg)
            tn_counter = Counter(
                (x.get('tournamentName') or '').strip() for x in sat_rows if x.get('tournamentName')
            )
            if not sat_rows:
                lines.append('(אין משחקי שבת מתועדים בטווח)')
            else:
                total = len(sat_rows)
                lines.append(f'סה״כ משחקי שבת בטווח: {total}')
                for name, cnt in tn_counter.most_common(15):
                    pct = round(100.0 * cnt / total, 1) if total else 0.0
                    lines.append(f'- {name}: {cnt} משחקים (~{pct}% ממשחקי השבת בטווח)')

        if want_top_team:
            lines.append('ספירת הופעות שמות קבוצות מכותרת המשחק (פורמט "קבוצה א - קבוצה ב"):')
            team_counter: Counter = Counter()
            for mg in hist_games:
                for team in self._teams_from_title(mg.get('gameTitle') or ''):
                    team_counter[team] += 1
            if not team_counter:
                lines.append('(לא ניתן לחשב — אין כותרות משחק מפורטות בטווח)')
            else:
                for name, cnt in team_counter.most_common(10):
                    lines.append(f'- {name}: {cnt} הופעות')

        return '\n'.join(lines) + '\n'
    
    def create_context_prompt(self, 
                            message: str, 
                            referee_detail: Optional[Dict] = None,
                            recent_messages: Optional[List] = None) -> str:
        """Create a context-aware prompt for the LLM with smart content selection"""
        
        # Base prompt
        prompt = f"""You are an AI assistant for a referee portal system. You help referees with questions about games, fields, rules, and procedures.

CONTEXT:
- Current message: {message}
- Language: Hebrew (respond in Hebrew)
- System: Referee Portal for football/soccer referees

KNOWLEDGE BASE:
"""
        
        # Smart content selection based on message keywords
        relevant_docs = self._select_relevant_documentation(message)
        max_content = 8000
        if isinstance(self.llmConfig, dict):
            max_content = int(self.llmConfig.get("max_content_size") or max_content)
        for doc_name, content in relevant_docs.items():
            truncated_content = content[:max_content] + "..." if len(content) > max_content else content
            prompt += f"\n--- {doc_name} ---\n{truncated_content}\n"
        
        # Add fields data only if relevant
        if self._is_field_related(message):
            prompt += "\n--- FIELDS DATA ---\n"
            # Limit to first 3 fields to keep prompt manageable
            field_count = 0
            for field_name, field_data in list(self.fields_data['content'].items()):
                #field_json = jsonHelper.save_to_json(field_data, ensure_ascii=False)
                field_json = field_data.get('findText')
                # Limit field data to 300 characters
                truncated_field = field_json[:300] + "..." if len(field_json) > 300 and False else field_json
                prompt += f"Field: {field_name}, Data: {truncated_field}\n"
                field_count += 1
                if field_count >= 3000:
                    break
        
        # Add referee context if available (limited)
        if referee_detail:
            prompt += f"\n--- REFEREE CONTEXT ---\n"
            prompt += f"Referee: {referee_detail.get('name', 'Unknown')}\n"
            prompt += f"Mobile: {referee_detail.get('mobileNo', 'Unknown')}\n"
            prompt += f"Area: {referee_detail.get('area', 'Unknown')}\n"
            if self._wants_personal_assignment_facts(message):
                try:
                    assignment_ctx = self._build_personal_assignment_context(message, referee_detail)
                    if assignment_ctx:
                        prompt += f"\n{assignment_ctx}"
                except Exception as e:
                    self.logger.error(f"LLM personal assignment context:", e)
        
        # Add recent conversation context (limited to last 3 messages)
        if recent_messages:
            prompt += f"\n--- RECENT CONVERSATION ---\n"
            recent_msgs = list(recent_messages.values())[-5:]  # Last 3 messages only
            for msg in recent_msgs:
                msg_text = msg.get('message', '')[:100]  # Limit message length
                prompt += f"{msg.get('from', 'User')}: {msg_text}\n"
        
        prompt += f"""

INSTRUCTIONS:
1. Respond in Hebrew
2. Be helpful and professional
3. If you don't know something, say so
4. If the question is about a field, use FIELDS DATA (כתובת, קישור/navigation וכו׳) and answer precisely
5. If the question is about rules, reference the appropriate documentation
6. If the question is about this referee's schedule or personal stats ("נתוני שיבוצים אישיים"), answer ONLY from that section; if empty, say no matching games were found
7. For "שבוע שעבר" use the dated week line in the personal data (Sunday–Saturday week)
8. For team statistics, use only the computed team-frequency lines; קבוצות יכולות להופיע פעמיים אם שובצת למשחקי בית וחוץ
9. If action is needed, specify what action

QUESTION: {message}

RESPONSE:"""
        
        return prompt
    
    def _select_relevant_documentation(self, message: str) -> Dict[str, str]:
        """Select relevant documentation based on message keywords"""
        message_lower = message.lower()
        relevant_docs = {}
        
        # Define keyword mappings
        keyword_mappings = {
            'rules': ['rules', 'חוקים', 'חוקה', 'תקנון', 'חוק'],
            'procedures': ['procedures', 'נוהל', 'נהלים', 'תהליך'],
            'fields': ['field', 'מגרש', 'מגרשים', 'שדה'],
            'games': ['game', 'משחק', 'משחקים', 'תחרות', 'שבוע שעבר', 'בקרוב', 'שנתון', 'קבוצה', 'שבת'],
            'referees': ['referee', 'שופט', 'שופטים', 'שיפוט', 'שפטתי'],
            'general': ['help', 'עזרה', 'מידע', 'איך']
        }
        
        # Find relevant categories
        relevant_categories = []
        for category, keywords in keyword_mappings.items():
            if any(keyword in message_lower for keyword in keywords):
                relevant_categories.append(category)
        
        # If no specific category found, include general docs
        if not relevant_categories:
            relevant_categories = ['general']
        
        # Select documents based on categories
        for doc_name, content in self.knowledge_base.items():
            doc_lower = doc_name.lower()
            
            # Check if document matches any relevant category
            for category in relevant_categories:
                if category in doc_lower or any(keyword in doc_lower for keyword in keyword_mappings.get(category, [])):
                    relevant_docs[doc_name] = content
                    break
            
            # Limit to 5 most relevant documents
            if len(relevant_docs) >= 5:
                break
        
        return relevant_docs
    
    def _is_field_related(self, message: str) -> bool:
        """Check if message is related to fields"""
        m = message.lower()
        extra = ('מגרש', 'שדה', 'כתובת', 'מגיעים', 'וייז', 'waze', 'ניווט')
        if any(k in m for k in extra):
            return True
        field_keywords = self.fields_data.get('variants') if isinstance(self.fields_data, dict) else None
        if not field_keywords:
            return False
        return any(keyword in m for keyword in field_keywords)
    
    async def get_llm_response(self, prompt: str) -> LLMResponse:
        """Get response from LLM"""
        try:
            # Use Bedrock client to get LLM response (synchronous call)
            # Try with fallback models if the primary model fails
            fallback_models = self.model_ids[1:] if len(self.model_ids) > 1 else []
            response = self.bedrock_client.invoke_model_async(
                model_id=self.model_id,
                prompt=prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                fallback_model_ids=fallback_models
            )
            
            if "error" in response:
                self.logger.error(f"LLM error: {response['error']}")
                return LLMResponse(
                    answer="מצטער, לא הצלחתי לעבד את הבקשה כרגע. אנא נסה שוב מאוחר יותר.",
                    confidence=0.0,
                    sources=[],
                    action_required=False,
                    action_type=None,
                    action_data=None
                )
            
            # Parse LLM response
            llm_text = response.get("text", "")
            if not llm_text:
                return LLMResponse(
                    answer="לא קיבלתי תשובה מהמערכת. אנא נסה שוב.",
                    confidence=0.0,
                    sources=[],
                    action_required=False,
                    action_type=None,
                    action_data=None
                )
            
            # Analyze response for actions
            action_required = self.analyze_response_for_actions(llm_text)
            action_type, action_data = self.extract_action_data(llm_text)
            
            return LLMResponse(
                answer=llm_text,
                confidence=0.8,  # Could be improved with confidence scoring
                sources=self.extract_sources(llm_text),
                action_required=action_required,
                action_type=action_type,
                action_data=action_data
            )
            
        except Exception as e:
            self.logger.error(f"Error getting LLM response:", e)
            return LLMResponse(
                answer="מצטער, יש בעיה טכנית. אנא נסה שוב מאוחר יותר.",
                confidence=0.0,
                sources=[],
                action_required=False,
                action_type=None,
                action_data=None
            )
    
    def analyze_response_for_actions(self, response: str) -> bool:
        """Analyze if response requires any actions"""
        action_indicators = [
            'צריך', 'נדרש', 'בקשה', 'בדוק', 'חפש', 'מצא',
            'need', 'required', 'request', 'check', 'search', 'find'
        ]
        
        return any(indicator in response.lower() for indicator in action_indicators)
    
    def extract_action_data(self, response: str) -> Tuple[Optional[str], Optional[Dict]]:
        """Extract action type and data from response"""
        # This is a simplified version - could be enhanced with more sophisticated parsing
        if 'מגרש' in response or 'field' in response.lower():
            return 'field_search', {'query': response}
        elif 'תמיכה' in response or 'support' in response.lower():
            return 'support_request', {'type': 'general'}
        elif 'טופס' in response or 'form' in response.lower():
            return 'document_request', {'type': 'form'}
        
        return None, None
    
    def extract_sources(self, response: str) -> List[str]:
        """Extract sources used in response"""
        sources = []
        for doc_name in self.knowledge_base.keys():
            if doc_name in response:
                sources.append(doc_name)
        return sources
    
    async def process_webhook_message(self, 
                                    message: str,
                                    referee_detail: Optional[Dict] = None,
                                    recent_messages: Optional[List] = None) -> LLMResponse:
        """Process webhook message through LLM"""
        
        try:
            # First check if it's a simple intent that doesn't need LLM
            simple_response = self.handle_simple_intent(message)
            if simple_response:
                return simple_response
            
            # Create context-aware prompt
            prompt = self.create_context_prompt(message, referee_detail, recent_messages)
            
            # Get LLM response
            llm_response = await self.get_llm_response(prompt)
            
            # Log the interaction
            self.log_interaction(message, llm_response)
            
            return llm_response
            
        except Exception as e:
            self.logger.error(f"Error processing webhook message:", e)
            return LLMResponse(
                answer="מצטער, יש בעיה טכנית. אנא נסה שוב מאוחר יותר.",
                confidence=0.0,
                sources=[],
                action_required=False
            )
    
    def handle_simple_intent(self, message: str) -> Optional[LLMResponse]:
        """Handle simple intents without LLM"""
        
        # Check for simple intents that have direct responses
        for intent, response in self.intent_phrases.items():
            if intent in message:
                if isinstance(response, list) and len(response) > 0:
                    return LLMResponse(
                        answer=response[0],
                        confidence=0.9,
                        sources=[intent],
                        action_required=False
                    )
                elif isinstance(response, str):
                    return LLMResponse(
                        answer=response,
                        confidence=0.9,
                        sources=[intent],
                        action_required=False
                    )
        
        return None
    
    def log_interaction(self, message: str, response: LLMResponse):
        """Log LLM interaction for analysis"""
        if not self.llmConfig.get('log_interactions'):
            return
        
        try:
            log_entry = {
                'timestamp': helpers.localNow().isoformat(),
                'message': message,
                'response': response.answer,
                'confidence': response.confidence,
                'sources': response.sources,
                'action_required': response.action_required,
                'action_type': response.action_type
            }
            
            # Save to database or file
            self.cacheService.dbClient.set(
                tableName=self.llmConfig.get('log_table'),
                value=log_entry,
                entityKey=f"interaction_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            
        except Exception as e:
            self.logger.error(f"Error logging interaction:", e)
    
    async def handle_field_search(self, query: str) -> str:
        """Handle field search requests"""
        try:
            # Use existing field search logic
            field_details = self.generate_field_details(query)
            return field_details
        except Exception as e:
            self.logger.error(f"Error in field search:", e)
            return "מצטער, לא הצלחתי למצוא מידע על המגרש המבוקש."
    
    def generate_field_details(self, field_to_search: str) -> str:
        """Generate field details (adapted from existing code)"""
        try:
            # This would be adapted from your existing generateFieldDetails method
            # For now, returning a placeholder
            return f"מידע על מגרש: {field_to_search}"
        except Exception as e:
            self.logger.error(f"Error generating field details:", e)
            return "לא נמצא מידע על המגרש המבוקש."
    
    def test_pdf_processing(self, pdf_url: str) -> Dict[str, Any]:
        """Test PDF processing capabilities"""
        result = {
            'pdf_available': PDF_AVAILABLE,
            'pdfplumber_available': PDFPLUMBER_AVAILABLE,
            'extracted_text': None,
            'text_length': 0,
            'error': None
        }
        
        try:
            if not PDF_AVAILABLE and not PDFPLUMBER_AVAILABLE:
                result['error'] = "No PDF processing libraries available"
                return result
            
            extracted_text = self.extract_text_from_pdf(pdf_url)
            result['extracted_text'] = extracted_text
            result['text_length'] = len(extracted_text) if extracted_text else 0
            
            if extracted_text.startswith("Error") or extracted_text.startswith("Could not"):
                result['error'] = extracted_text
                
        except Exception as e:
            result['error'] = str(e)
            
        return result

# Integration with existing webhook
class LLMWebhookHandler:
    """Handler to integrate LLM with existing webhook"""
    
    def __init__(self, llm_integration: LLMWebhookIntegration):
        self.llm = llm_integration
    
    async def enhance_webhook_response(self, 
                                     incoming_request: Dict,
                                     referee_detail: Optional[Dict] = None,
                                     existing_response: Optional[str] = None) -> Tuple[str, bool]:
        """Enhance webhook response with LLM"""
        
        message_body = incoming_request.get('messageBody', '')
        
        if not message_body:
            return existing_response or "", False
        
        try:
            # Get recent messages for context
            recent_messages = []
            if referee_detail:
                mobile_no = referee_detail.get('mobileNo')
                if mobile_no:
                    recent_messages = self.llm.cacheService.getRefereeMessages(mobileNo=mobile_no, direction='FROM')
            
            # Process through LLM
            llm_response = await self.llm.process_webhook_message(
                message=message_body,
                referee_detail=referee_detail,
                recent_messages=recent_messages
            )
            
            # If LLM response is better than existing, use it
            if llm_response.confidence > 0.7 and llm_response.answer:
                return llm_response.answer, True
            
            # Otherwise, use existing response
            return existing_response or "", False
            
        except Exception as e:
            self.llm.logger.error(f"Error enhancing webhook response:", e)
            return existing_response or "", False

# Usage example
async def setup_llm_integration(config: Dict[str, Any]) -> LLMWebhookHandler:
    """Setup LLM integration for webhook"""
    
    # Initialize components
    logger = Logger()
    bedrock_client = BedrockClient()
    cacheService = None  # Initialize your DB client
    
    # Create LLM integration
    llm_integration = LLMWebhookIntegration(
        logger=logger,
        bedrock_client=bedrock_client,
        cacheService=cacheService,
        docs_service_url=config.get('docsServiceUrlBase'),
        config=config
    )
    
    # Create webhook handler
    handler = LLMWebhookHandler(llm_integration)
    
    return handler
