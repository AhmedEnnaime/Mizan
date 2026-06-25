import json


MORNING_BRIEFING_SYSTEM = """You are an AI investment assistant specializing in the Casablanca Stock Exchange (BVC).
Your user is a beginner investor in Morocco learning as they invest. Explain reasoning in clear, educational terms — never use jargon without defining it.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


ALERT_SYSTEM = """You are a real-time investment alert assistant for a beginner investor on the Casablanca Stock Exchange (BVC).
Write clear, short, educational alerts. Explain what happened and why it matters in simple terms.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


def build_morning_briefing_prompt(context: dict) -> str:
    return f"""Analyze today's BVC market data and produce a morning briefing.

MARKET DATA:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure (no extra fields):
{{
  "market_pulse": {{
    "masi": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "gold": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "oil": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "eur_mad": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "cac40": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "phosphate_proxy": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}}
  }},
  "whats_happening": "<3-4 sentence summary of today's key events and their BVC relevance, in plain language>",
  "ai_picks": [
    {{
      "ticker": "<BVC ticker>",
      "name": "<company name>",
      "label": "<BUY|WATCH|AVOID>",
      "strategy": "<1-2 sentence tactical recommendation>",
      "explanation": "<3-4 sentence educational explanation for a beginner, including what technical signal supports this>"
    }}
  ],
  "this_week": ["<forward-looking event 1>", "<event 2>", "<event 3>"]
}}

Rules:
- Select 3-5 stocks for ai_picks; base decisions on technical signals in the data, not company fame
- Each explanation must define at least one technical term used (e.g. RSI, MACD, support level)
- Use null for any market_pulse value not present in the data"""


def build_alert_prompt(alert_type: str, context: dict) -> str:
    return f"""Generate a real-time BVC investment alert.

ALERT TYPE: {alert_type}
CONTEXT:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure:
{{
  "alert_type": "{alert_type}",
  "ticker": "<affected BVC ticker or null>",
  "headline": "<10-15 word headline summarizing the event>",
  "what_happened": "<2-3 sentences describing what occurred>",
  "what_it_means": "<2-3 sentences explaining portfolio impact for a beginner investor>",
  "educational_lesson": "<1-2 sentences: one investing concept this event illustrates>"
}}"""
