import json


_ENRICHMENT_KEYS = {"sector_map", "past_performance", "reddit_discussions", "paper_portfolio"}


def _prune_context_for_dump(context: dict) -> dict:
    pruned = {k: v for k, v in context.items() if k not in _ENRICHMENT_KEYS}
    # Also strip per-stock profile keys
    if "bvc" in pruned and "stocks" in pruned.get("bvc", {}).get("data", {}):
        stocks = [
            {k: v for k, v in s.items() if k != "profile"}
            for s in pruned["bvc"]["data"]["stocks"]
        ]
        pruned = {**pruned, "bvc": {**pruned["bvc"], "data": {**pruned["bvc"]["data"], "stocks": stocks}}}
    return pruned


MORNING_BRIEFING_SYSTEM = """You are an AI investment assistant specializing in the Casablanca Stock Exchange (BVC).
Your user is a beginner investor in Morocco learning as they invest. Explain reasoning in clear, educational terms — never use jargon without defining it.
You have access to structured company profiles describing each BVC stock's business model, key revenue drivers, and macro sensitivities. Use these when explaining why a macro event (e.g. rising oil, weak dirham) affects a specific company.
You also have a record of your past pick performance over the last 30 days — factor this into your confidence level.
Stock-specific news articles surface targeted coverage of individual BVC companies — treat them as a supplementary signal, not a primary one.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


ALERT_SYSTEM = """You are a real-time investment alert assistant for a beginner investor on the Casablanca Stock Exchange (BVC).
Write clear, short, educational alerts. Explain what happened and why it matters in simple terms.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


def _build_company_profiles_block(context: dict) -> str:
    stocks = context.get("bvc", {}).get("data", {}).get("stocks", [])
    lines = []
    for stock in stocks:
        profile = stock.get("profile")
        if not profile:
            continue
        ticker = stock.get("ticker", "")
        desc = profile.get("description", "")
        drivers = ", ".join(profile.get("key_drivers", []))
        sensitivity = "; ".join(
            f"{k}: {v}" for k, v in (profile.get("macro_sensitivity") or {}).items()
        )
        line = f"{ticker}: {desc}"
        if drivers:
            line += f" Key drivers: {drivers}."
        if sensitivity:
            line += f" Macro: {sensitivity}."
        lines.append(line)
    if not lines:
        return ""
    return "COMPANY PROFILES:\n" + "\n".join(lines)


def _build_sector_map_block(context: dict) -> str:
    sector_map = context.get("sector_map")
    if not sector_map:
        return ""
    lines = ["SECTOR MAP (use when linking macro events to specific sectors):"]
    for sector, data in sector_map.items():
        stocks = ", ".join(data.get("stocks", []))
        impacts = {k: v for k, v in data.items() if k.endswith("_impact")}
        impact_str = "; ".join(f"{k.replace('_impact','')}: {v}" for k, v in list(impacts.items())[:3])
        lines.append(f"  {sector} [{stocks}]: {impact_str}")
    return "\n".join(lines)


def _build_past_performance_block(context: dict) -> str:
    pp = context.get("past_performance")
    if not pp:
        return ""
    lines = [
        "YOUR PAST PERFORMANCE — last 30 days (factor this into confidence):",
        f"  {pp['accuracy_summary']}",
    ]
    misses = [p for p in pp.get("picks", []) if p.get("outcome") == "incorrect"]
    if misses:
        miss = misses[0]
        lines.append(
            f"  Recent miss: {miss['ticker']} {miss['pick']} at {miss['price_at_pick']} → {miss.get('change_pct', 'N/A')}% after {pp['window_days']} days"
        )
    return "\n".join(lines)


def _build_portfolio_block(context: dict) -> str:
    positions = context.get("paper_portfolio")
    if not positions:
        return ""
    lines = ["PAPER PORTFOLIO (your virtual BVC positions — reference these when making picks):"]
    for p in positions:
        line = f"  {p['ticker']}: {p['shares']} shares @ avg {p['avg_cost_mad']:.2f} MAD"
        if p.get("current_price") is not None:
            sign = "+" if p["pnl_pct"] >= 0 else ""
            line += (
                f" | today {p['current_price']:.2f} MAD"
                f" | {sign}{p['pnl_pct']:.1f}% ({sign}{p['pnl_mad']:.0f} MAD unrealised)"
            )
        else:
            line += " | today N/A"
        lines.append(line)
    return "\n".join(lines)


def _build_reddit_block(context: dict) -> str:
    articles = context.get("reddit_discussions")
    if not articles:
        return ""
    lines = ["STOCK-SPECIFIC NEWS (Google News — supplementary signal only):"]
    for a in articles[:8]:
        ticker_tag = f"[{a['ticker']}] " if a.get("ticker") else ""
        pub = (a.get("published", "") or "")[:16]
        lines.append(f"  {ticker_tag}\"{a['title']}\" — {a.get('source', '')} {pub}")
    return "\n".join(lines)


def build_morning_briefing_prompt(context: dict) -> str:
    blocks = [
        _build_company_profiles_block(context),
        _build_sector_map_block(context),
        _build_past_performance_block(context),
        _build_reddit_block(context),
        _build_portfolio_block(context),
    ]
    enrichment_section = "\n\n".join(b for b in blocks if b)

    return f"""Analyze today's BVC market data and produce a morning briefing.

{enrichment_section + chr(10) + chr(10) if enrichment_section else ""}MARKET DATA:
{json.dumps(_prune_context_for_dump(context), indent=2, ensure_ascii=False, default=str)}

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
- Use null for any market_pulse value not present in the data
- Use the company profiles and sector map to ground explanations in the company's actual business drivers"""


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
