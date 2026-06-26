# Logging Enhancement Design

## Goal

Replace Mizan's single flat log file with a structured observability layer that makes it trivial to answer three questions: did the morning run succeed, what was degraded if it didn't, and what exactly happened when something broke.

## Architecture

Four components added on top of the existing logging skeleton:

```
observability/
  __init__.py
  run_context.py   — run ID generation + logging filter that stamps every line
  health.py        — RunHealthCollector: records step outcomes, renders email footer

main.py            — upgraded setup_logging(): rotation, two files, RunIdFilter
scheduler/jobs.py  — wires RunHealthCollector through run_morning_briefing()
delivery/email.py  — send_morning_briefing() accepts optional health_html footer
logs/
  mizan.log        — INFO+, rotating 5 MB × 7 backups
  errors.log       — WARNING+, rotating 2 MB × 10 backups
  debug/           — per-failure JSON snapshots (written only on unrecoverable error)
Makefile           — make logs, make errors, make debug-last
```

## Global Constraints

- Python stdlib only for logging (`logging`, `logging.handlers`, `contextvars`) — no new dependencies
- All existing log call sites (`logger.info`, `logger.warning`, `logger.error`) unchanged — the run ID is injected automatically via a filter, not by modifying every call site
- Debug snapshots are written only on unrecoverable failures (Claude API exhausted, email delivery failed after retries) — not for expected silent failures (single enricher timeout, one scraper failing)
- The health footer is appended to the morning briefing email only — alert emails are unchanged
- `dry_run=True` mode prints the health summary to stdout instead of appending to email
- Commit messages: single short line, no body, no AI attribution

---

## Component 1 — Log Infrastructure (`main.py`)

Replace `logging.basicConfig()` with explicit handler setup.

**Two rotating file handlers:**

| File | Level | Max size | Backups |
|---|---|---|---|
| `logs/mizan.log` | INFO+ | 5 MB | 7 |
| `logs/errors.log` | WARNING+ | 2 MB | 10 |

Plus the existing `StreamHandler(sys.stdout)` at INFO+, unchanged.

**Format** (all handlers):
```
%(asctime)s [%(levelname)-8s] [%(run_id)-10s] %(name)s: %(message)s
```

Example output:
```
2026-06-26 08:31:04 [INFO    ] [run-0831  ] scheduler.jobs: Running morning briefing
2026-06-26 08:31:09 [WARNING ] [run-0831  ] enrichment.reddit: failed to fetch r/Maroc: timeout
2026-06-26 08:33:12 [INFO    ] [run-0831  ] scheduler.jobs: Briefing complete | stocks:37 news:43 enrichers:4/5 sent:✓ [2m08s]
```

Lines outside a run (scheduler startup, etc.) show `run_id = "-"`.

**`setup_logging()` in `main.py`:**
```python
from logging.handlers import RotatingFileHandler
from observability.run_context import RunIdFilter

def setup_logging() -> None:
    LOG_DIR = LOG_PATH.parent
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] [%(run_id)-10s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_filter = RunIdFilter()

    handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_DIR / "mizan.log", maxBytes=5_242_880, backupCount=7, encoding="utf-8"),
        RotatingFileHandler(LOG_DIR / "errors.log", maxBytes=2_097_152, backupCount=10, encoding="utf-8"),
    ]
    handlers[2].setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(run_filter)
        root.addHandler(h)
```

---

## Component 2 — Run ID (`observability/run_context.py`)

```python
import logging
from contextvars import ContextVar

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

def new_run_id() -> str:
    from datetime import datetime
    import pytz
    now = datetime.now(pytz.timezone("Africa/Casablanca"))
    return f"run-{now:%H%M}"

def set_run_id(rid: str) -> None:
    _run_id.set(rid)

def get_run_id() -> str:
    return _run_id.get()

class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id.get()
        return True
```

**How it works:** `RunIdFilter` is attached to every handler in `setup_logging()`. Before any log record is written, the filter reads the current `ContextVar` value and stamps `record.run_id`. APScheduler runs each job in its own thread; `ContextVar` is thread-safe and isolates each run's ID automatically.

At the start of `run_morning_briefing()`:
```python
from observability.run_context import new_run_id, set_run_id
rid = new_run_id()
set_run_id(rid)
```

---

## Component 3 — Health Collector (`observability/health.py`)

```python
import time
from dataclasses import dataclass, field

@dataclass
class RunHealthCollector:
    run_id: str
    date: str
    _start: float = field(default_factory=time.monotonic, repr=False)

    stocks_collected: int = 0
    stocks_total: int = 0
    bvc_cached: bool = False
    news_articles: int = 0
    enrichers_ok: int = 0
    enrichers_total: int = 5
    reddit_ok: bool = False
    masi_rows: int = 0
    ai_ok: bool = False
    email_sent: bool = False
    warnings: list[str] = field(default_factory=list)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def duration_s(self) -> int:
        return int(time.monotonic() - self._start)

    def to_log_line(self) -> str:
        mins, secs = divmod(self.duration_s, 60)
        sent = "✓" if self.email_sent else "✗"
        ai = "✓" if self.ai_ok else "✗"
        cached = " (cached)" if self.bvc_cached else ""
        return (
            f"Briefing complete | "
            f"stocks:{self.stocks_collected}/{self.stocks_total}{cached} "
            f"news:{self.news_articles} "
            f"enrichers:{self.enrichers_ok}/{self.enrichers_total} "
            f"ai:{ai} sent:{sent} "
            f"[{mins}m{secs:02d}s]"
        )

    def to_html_footer(self) -> str:
        mins, secs = divmod(self.duration_s, 60)

        def row(label, value, ok=True, note=""):
            icon = "✓" if ok else "⚠"
            color = "#2d7a2d" if ok else "#b85c00"
            note_html = f' <span style="color:#888;font-size:11px">{note}</span>' if note else ""
            return (
                f'<tr>'
                f'<td style="padding:2px 12px 2px 0;color:#555">{label}</td>'
                f'<td style="padding:2px 12px 2px 0">{value}</td>'
                f'<td style="color:{color}">{icon}{note_html}</td>'
                f'</tr>'
            )

        warn_note = "; ".join(self.warnings) if self.warnings else ""
        cached_label = "Stocks collected (cached)" if self.bvc_cached else "Stocks collected"
        enricher_ok = self.enrichers_ok == self.enrichers_total

        rows = "".join([
            row(cached_label, f"{self.stocks_collected} / {self.stocks_total}", self.stocks_collected > 0),
            row("News articles", str(self.news_articles), self.news_articles > 0),
            row("Enrichers", f"{self.enrichers_ok} / {self.enrichers_total}", enricher_ok, warn_note if not enricher_ok else ""),
            row("MASI history", f"{self.masi_rows} rows", self.masi_rows >= 5),
            row("AI analysis", "✓" if self.ai_ok else "unavailable", self.ai_ok),
            row("Email delivered", "✓" if self.email_sent else "failed", self.email_sent),
            row("Duration", f"{mins}m {secs:02d}s", True),
        ])

        return (
            f'<hr style="margin-top:32px;border:none;border-top:1px solid #ddd">'
            f'<p style="font-family:monospace;font-size:12px;color:#888">'
            f'Run health &nbsp;·&nbsp; {self.date} &nbsp;·&nbsp; {self.run_id}'
            f'</p>'
            f'<table style="font-family:monospace;font-size:12px;border-collapse:collapse">'
            f'{rows}'
            f'</table>'
        )
```

---

## Component 4 — Debug Snapshot (`scheduler/jobs.py`)

A private helper called inside `run_morning_briefing()` when an unrecoverable failure occurs.

**Triggers:**
- Claude API fails after all retries (`"error"` in `analysis` AND email is fallback)
- Email delivery fails after both attempts
- `collect_and_persist()` raises an uncaught exception

**Output path:** `logs/debug/{date}-{run_id}.json`

**Contents:**
```json
{
  "run_id": "run-0831",
  "date": "2026-06-26",
  "timestamp": "2026-06-26T08:33:12Z",
  "failed_at": "email_delivery",
  "exception": "SMTPAuthenticationError: ...",
  "traceback": "...",
  "health": { "stocks_collected": 37, "ai_ok": true, "email_sent": false, "warnings": [] },
  "context_snapshot": {
    "date": "...",
    "bvc": { "success": true, "data": { "masi": {}, "stocks": [...] } },
    "news": { "success": true, "data": { "articles": [...] } },
    "commodities": {},
    "macro": {}
  }
}
```

**Context snapshot excludes:** `sector_map`, per-stock `profile` fields, `reddit_discussions`, `past_performance` — all reconstructable from static files or DB. This keeps the snapshot file small and readable.

**Private helper signature:**
```python
def _write_debug_snapshot(
    run_id: str,
    date: str,
    failed_at: str,
    exc: Exception,
    context: dict,
    health: "RunHealthCollector",
) -> None:
```

Silent-fail: if writing the snapshot itself fails (e.g. disk full), log a warning and continue — never let snapshot writing crash the run.

---

## Component 5 — Email Footer (`delivery/email.py`)

`send_morning_briefing()` gains an optional `health_html` parameter:

```python
def send_morning_briefing(html_body: str, health_html: str | None = None) -> None:
    if health_html:
        html_body = html_body.replace("</body>", f"{health_html}</body>")
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    send_email(f"BVC Morning Briefing — {date_str}", html_body)
```

Alert emails (`send_alert`) are unchanged.

---

## Component 6 — Makefile Targets

```makefile
logs:
	tail -f logs/mizan.log

errors:
	cat logs/errors.log

debug-last:
	@latest=$$(ls -t logs/debug/*.json 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "No debug snapshots found."; \
	else echo "=== $$latest ===" && python3 -m json.tool "$$latest"; fi
```

Added to `.PHONY`.

---

## Wiring in `scheduler/jobs.py`

**`enrichment/__init__.py` returns enricher stats** so `jobs.py` can populate the health collector without knowing enricher internals. Return type changes from `dict` to `tuple[dict, dict]`:

```python
# enrichment/__init__.py
def enrich(context: dict) -> tuple[dict, dict]:
    # returns (enriched_context, {"ok": 4, "total": 5, "failed": ["reddit"]})
```

`run_morning_briefing()` updated flow (key changes only):

```python
def run_morning_briefing(dry_run: bool = False) -> None:
    from observability.run_context import new_run_id, set_run_id
    from observability.health import RunHealthCollector
    from storage.db import get_masi_history

    rid = new_run_id()
    set_run_id(rid)
    date_str = datetime.now(MOROCCO_TZ).date().isoformat()
    health = RunHealthCollector(run_id=rid, date=date_str)
    logger.info("Running morning briefing")

    # Step 1: collect
    context = collect_and_persist()
    stocks = context["bvc"]["data"].get("stocks", [])
    health.stocks_collected = len(stocks)
    health.stocks_total = len(stocks)
    health.bvc_cached = any(s.get("_cached") for s in stocks)
    health.news_articles = len(context["news"]["data"].get("articles", []))

    # Step 2: enrich — returns (context, stats)
    try:
        context, enrich_stats = enrich(context)
        health.enrichers_ok = enrich_stats["ok"]
        health.enrichers_total = enrich_stats["total"]
        health.reddit_ok = bool(context.get("reddit_discussions"))
        health.masi_rows = len(get_masi_history(days=252))
        for name in enrich_stats.get("failed", []):
            health.add_warning(f"{name} enricher failed")
    except Exception as exc:
        health.add_warning(f"enrichment pipeline: {exc}")

    # Step 3: AI analysis
    analysis = run_morning_analysis(context)
    health.ai_ok = "error" not in analysis

    if not health.ai_ok:
        # existing fallback path — also write debug snapshot
        _write_debug_snapshot(rid, date_str, "ai_analysis",
                              Exception(analysis["error"]), context, health)
        # ... existing fallback html + save_briefing + optional send ...
        logger.info(health.to_log_line())
        return

    html = format_morning_briefing(analysis, date_str)
    save_briefing(date_str, html, context)

    try:
        record_picks(analysis, context)
    except Exception as exc:
        health.add_warning(f"record_picks: {exc}")

    # Step 4: deliver
    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print(health.to_log_line())
    else:
        last_exc = None
        for attempt in range(2):
            try:
                send_morning_briefing(html, health_html=health.to_html_footer())
                health.email_sent = True
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(f"Email attempt {attempt + 1} failed: {exc}")
        if last_exc:
            _write_debug_snapshot(rid, date_str, "email_delivery", last_exc, context, health)
            logger.error(f"Email delivery failed after 2 attempts: {last_exc}", exc_info=True)

    logger.info(health.to_log_line())
```

**dry_run note:** In dry_run mode the health log line is printed to stdout but no email is sent and no footer is generated. `health.email_sent` remains `False` which is correct — dry runs never deliver.

---

## Tests

**`tests/observability/test_run_context.py`** (3 tests):
- `RunIdFilter` stamps `record.run_id` from ContextVar
- `new_run_id()` returns string matching `run-\d{4}` pattern
- Multiple threads get independent run IDs (thread isolation)

**`tests/observability/test_health.py`** (4 tests):
- `to_log_line()` contains all key fields
- `to_html_footer()` contains run_id, date, and all section labels
- `add_warning()` appears in footer with ⚠ icon
- `duration_s` increases over time

**`tests/test_jobs.py`** additions (3 tests):
- Debug snapshot written to `logs/debug/` on AI failure
- Debug snapshot written on email delivery failure
- No debug snapshot written on successful run

**`tests/test_email.py`** additions (1 test):
- `send_morning_briefing()` with `health_html` appends footer before `</body>`
