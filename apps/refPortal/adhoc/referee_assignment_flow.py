# Re-run the generation of the ManyChat flow JSON structure after code execution state reset
import json
from pathlib import Path

flow = {
    "version": "2.0",
    "metadata": {
        "name": "Referee Game Assignment",
        "description": "Notify referees of new game assignments and collect confirmations"
    },
    "root_block": {
        "name": "Start",
        "type": "message",
        "messages": [
            {
                "type": "text",
                "text": (
                    "📋 משחק חדש הוקצה לך:\n"
                    "🏟 {{venue}}\n"
                    "🕓 {{time}}\n"
                    "⚽ {{teams}}\n\n"
                    "אתה מאשר קבלת המשחק?\n"
                    "מספר מזהה: {{game_id}}"
                ),
                "actions": [],
                "replies": [
                    {
                        "type": "quick_reply",
                        "caption": "✅ מאשר",
                        "payload": "referee_accept_game"
                    },
                    {
                        "type": "quick_reply",
                        "caption": "❌ לא מאשר",
                        "payload": "referee_reject_game"
                    }
                ]
            }
        ]
    }
}

# Save to file
output_path = Path("./adhoc/referee_assignment_flow.json")
output_path.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")

output_path.name
