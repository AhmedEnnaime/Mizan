import json
import re
import logging
import anthropic

from config import ANTHROPIC_API_KEY, MORNING_BRIEFING_MODEL, ALERT_MODEL
from agent.prompts import (
    MORNING_BRIEFING_SYSTEM, ALERT_SYSTEM,
    build_morning_briefing_prompt, build_alert_prompt,
)

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Empty response from model")
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def run_morning_analysis(context: dict) -> dict:
    prompt = build_morning_briefing_prompt(context)
    for attempt in range(2):
        try:
            message = client.messages.create(
                model=MORNING_BRIEFING_MODEL,
                max_tokens=4096,
                system=MORNING_BRIEFING_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return _extract_json(message.content[0].text)
        except Exception as exc:
            logger.error(f"Morning analysis attempt {attempt + 1} failed: {exc}", exc_info=True)
    return {"error": "AI analysis unavailable", "raw_context": context}


def run_alert_analysis(alert_type: str, context: dict) -> dict:
    prompt = build_alert_prompt(alert_type, context)
    for attempt in range(2):
        try:
            message = client.messages.create(
                model=ALERT_MODEL,
                max_tokens=2048,
                system=ALERT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return _extract_json(message.content[0].text)
        except Exception as exc:
            logger.error(f"Alert analysis attempt {attempt + 1} failed: {exc}", exc_info=True)
    return {"error": "AI analysis unavailable", "context": context}
