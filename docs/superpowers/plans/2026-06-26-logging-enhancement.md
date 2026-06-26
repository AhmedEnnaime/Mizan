# Logging Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add run-ID-stamped rotating logs, a health summary appended to every morning briefing email, and a JSON debug snapshot written on unrecoverable failures.

**Architecture:** A new `observability/` module provides a thread-safe `ContextVar`-based run ID (injected into all log lines via a `logging.Filter`) and a `RunHealthCollector` dataclass that records step outcomes and renders an HTML email footer. `scheduler/jobs.py` wires the collector through `run_morning_briefing()`, writing a debug snapshot to `logs/debug/` on failure.

**Tech Stack:** Python stdlib only — `logging`, `logging.handlers.RotatingFileHandler`, `contextvars.ContextVar`, `dataclasses`, `json`, `traceback`. No new pip dependencies.

## Global Constraints

- No new pip dependencies — stdlib only
- All existing `logger.info/warning/error` call sites unchanged — run ID injected automatically via filter
- Debug snapshots written ONLY on unrecoverable failures: Claude API exhausted, email delivery failed after 2 attempts, uncaught exception in collect_and_persist
- Health footer appended to morning briefing email only — `send_alert()` is unchanged
- `dry_run=True` prints the health log line to stdout; no email sent and no footer generated
- Commit messages: single short line, no body, no AI attribution
- Log format: `%(asctime)s [%(levelname)-8s] [%(run_id)-10s] %(name)s: %(message)s` — identical across all handlers
- `logs/mizan.log`: INFO+, 5 MB rotating, 7 backups
- `logs/errors.log`: WARNING+, 2 MB rotating, 10 backups
- Run ID format: `run-HHMM` (Morocco time)
- Debug snapshot path: `logs/debug/{date}-{run_id}.json`

---

## File Map

| Action | Path | Purpose |
|---|---|---|
| Create | `observability/__init__.py` | empty package marker |
| Create | `observability/run_context.py` | RunIdFilter, ContextVar, new_run_id/set_run_id/get_run_id |
| Create | `observability/health.py` | RunHealthCollector dataclass |
| Modify | `main.py:20-29` | replace setup_logging() with rotating handlers + RunIdFilter |
| Modify | `enrichment/__init__.py:6` | change return type to `tuple[dict, dict]` |
| Modify | `delivery/email.py:29-31` | add `health_html` param to send_morning_briefing |
| Modify | `scheduler/jobs.py` | add _write_debug_snapshot, rewrite run_morning_briefing |
| Modify | `Makefile` | add logs/errors/debug-last targets |
| Create | `tests/observability/__init__.py` | empty |
| Create | `tests/observability/test_run_context.py` | 4 tests |
| Create | `tests/observability/test_health.py` | 4 tests |
| Modify | `tests/enrichment/test_enrichment_init.py` | unpack tuple return |
| Modify | `tests/test_delivery.py` | 2 new tests for health_html param |
| Modify | `tests/test_jobs.py` | update enrich mocks to return tuple, add 2 new tests |

---

### Task 1: observability/run_context.py + main.py logging setup

**Files:**
- Create: `observability/__init__.py`
- Create: `observability/run_context.py`
- Modify: `main.py:20-29` (replace `setup_logging()`)
- Create: `tests/observability/__init__.py`
- Create: `tests/observability/test_run_context.py`

**Interfaces:**
- Produces: `RunIdFilter(logging.Filter)`, `new_run_id() -> str`, `set_run_id(str) -> None`, `get_run_id() -> str`
- Task 2 (health.py) does not use this. Task 5 (jobs.py) imports `new_run_id` and `set_run_id`.

---

- [ ] **Step 1: Write the failing tests**

Create `tests/observability/__init__.py` (empty) and `tests/observability/test_run_context.py`:

```python
import logging
import re
import threading


def test_run_id_filter_stamps_record():
    from observability.run_context import RunIdFilter, set_run_id
    set_run_id("run-0830")
    f = RunIdFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
    f.filter(record)
    assert record.run_id == "run-0830"


def test_run_id_default_is_dash():
    from observability import run_context
    run_context._run_id.set("-")
    assert run_context.get_run_id() == "-"


def test_new_run_id_format():
    from observability.run_context import new_run_id
    rid = new_run_id()
    assert re.match(r"^run-\d{4}$", rid), f"Unexpected format: {rid}"


def test_thread_isolation():
    from observability.run_context import set_run_id, get_run_id
    results = {}

    def worker(name, rid):
        set_run_id(rid)
        import time; time.sleep(0.05)
        results[name] = get_run_id()

    t1 = threading.Thread(target=worker, args=("a", "run-0100"))
    t2 = threading.Thread(target=worker, args=("b", "run-0200"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["a"] == "run-0100"
    assert results["b"] == "run-0200"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Desktop/Mizan && .venv/bin/python -m pytest tests/observability/test_run_context.py -v
```

Expected: 4 FAILED (ModuleNotFoundError: No module named 'observability')

- [ ] **Step 3: Create observability/__init__.py**

```python
```

(empty file)

- [ ] **Step 4: Create observability/run_context.py**

```python
import logging
from contextvars import ContextVar
from datetime import datetime

import pytz

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

_MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def new_run_id() -> str:
    now = datetime.now(_MOROCCO_TZ)
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

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/observability/test_run_context.py -v
```

Expected: 4 PASSED

- [ ] **Step 6: Replace setup_logging() in main.py**

Current `main.py:20-29`:
```python
def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )
```

Replace with:
```python
def setup_logging() -> None:
    from logging.handlers import RotatingFileHandler
    from observability.run_context import RunIdFilter

    log_dir = LOG_PATH.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] [%(run_id)-10s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_filter = RunIdFilter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    mizan_handler = RotatingFileHandler(
        log_dir / "mizan.log", maxBytes=5_242_880, backupCount=7, encoding="utf-8"
    )
    errors_handler = RotatingFileHandler(
        log_dir / "errors.log", maxBytes=2_097_152, backupCount=10, encoding="utf-8"
    )
    errors_handler.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in [stdout_handler, mizan_handler, errors_handler]:
        h.setFormatter(fmt)
        h.addFilter(run_filter)
        root.addHandler(h)
```

- [ ] **Step 7: Run the full test suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add observability/__init__.py observability/run_context.py main.py \
        tests/observability/__init__.py tests/observability/test_run_context.py
git commit -m "feat: add observability module with run ID and rotating log handlers"
```

---

### Task 2: RunHealthCollector

**Files:**
- Create: `observability/health.py`
- Create: `tests/observability/test_health.py`

**Interfaces:**
- Consumes: nothing from Task 1 (health.py is standalone)
- Produces:
  ```python
  class RunHealthCollector:
      run_id: str
      date: str
      stocks_collected: int
      stocks_total: int
      bvc_cached: bool
      news_articles: int
      enrichers_ok: int
      enrichers_total: int
      reddit_ok: bool
      masi_rows: int
      ai_ok: bool
      email_sent: bool
      warnings: list[str]
      def add_warning(self, msg: str) -> None
      def to_log_line(self) -> str
      def to_html_footer(self) -> str
  ```
- Task 5 (jobs.py) imports `RunHealthCollector` and calls all methods listed above.

---

- [ ] **Step 1: Write the failing tests**

Create `tests/observability/test_health.py`:

```python
import time
from observability.health import RunHealthCollector


def test_to_log_line_contains_key_fields():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    h.stocks_collected = 37
    h.stocks_total = 37
    h.news_articles = 43
    h.enrichers_ok = 5
    h.enrichers_total = 5
    h.ai_ok = True
    h.email_sent = True
    line = h.to_log_line()
    assert "stocks:37/37" in line
    assert "news:43" in line
    assert "enrichers:5/5" in line
    assert "ai:✓" in line
    assert "sent:✓" in line


def test_to_html_footer_contains_run_id_and_date():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    html = h.to_html_footer()
    assert "run-0830" in html
    assert "2026-06-26" in html
    assert "Stocks collected" in html
    assert "Email delivered" in html


def test_add_warning_appears_in_footer():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    h.enrichers_ok = 4
    h.enrichers_total = 5
    h.add_warning("reddit enricher failed")
    html = h.to_html_footer()
    assert "reddit enricher failed" in html
    assert "⚠" in html


def test_duration_s_increases():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    d1 = h.duration_s
    time.sleep(0.12)
    d2 = h.duration_s
    assert d2 >= d1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/observability/test_health.py -v
```

Expected: 4 FAILED (ImportError: cannot import name 'RunHealthCollector')

- [ ] **Step 3: Create observability/health.py**

```python
import time
from dataclasses import dataclass, field


@dataclass
class RunHealthCollector:
    run_id: str
    date: str
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

    def __post_init__(self) -> None:
        self._start: float = time.monotonic()

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

        def row(label: str, value: str, ok: bool = True, note: str = "") -> str:
            icon = "✓" if ok else "⚠"
            color = "#2d7a2d" if ok else "#b85c00"
            note_html = (
                f' <span style="color:#888;font-size:11px">{note}</span>' if note else ""
            )
            return (
                f"<tr>"
                f'<td style="padding:2px 12px 2px 0;color:#555">{label}</td>'
                f'<td style="padding:2px 12px 2px 0">{value}</td>'
                f'<td style="color:{color}">{icon}{note_html}</td>'
                f"</tr>"
            )

        warn_note = "; ".join(self.warnings)
        enricher_ok = self.enrichers_ok == self.enrichers_total
        cached_label = "Stocks collected (cached)" if self.bvc_cached else "Stocks collected"

        rows = "".join([
            row(cached_label, f"{self.stocks_collected} / {self.stocks_total}", self.stocks_collected > 0),
            row("News articles", str(self.news_articles), self.news_articles > 0),
            row(
                "Enrichers",
                f"{self.enrichers_ok} / {self.enrichers_total}",
                enricher_ok,
                warn_note if not enricher_ok else "",
            ),
            row("MASI history", f"{self.masi_rows} rows", self.masi_rows >= 5),
            row("AI analysis", "✓" if self.ai_ok else "unavailable", self.ai_ok),
            row("Email delivered", "✓" if self.email_sent else "failed", self.email_sent),
            row("Duration", f"{mins}m {secs:02d}s", True),
        ])

        return (
            '<hr style="margin-top:32px;border:none;border-top:1px solid #ddd">'
            f'<p style="font-family:monospace;font-size:12px;color:#888">'
            f"Run health &nbsp;·&nbsp; {self.date} &nbsp;·&nbsp; {self.run_id}"
            "</p>"
            '<table style="font-family:monospace;font-size:12px;border-collapse:collapse">'
            f"{rows}"
            "</table>"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/observability/test_health.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add observability/health.py tests/observability/test_health.py
git commit -m "feat: add RunHealthCollector"
```

---

### Task 3: enrichment/__init__.py — return enricher stats

**Files:**
- Modify: `enrichment/__init__.py:6-16`
- Modify: `tests/enrichment/test_enrichment_init.py`

**Interfaces:**
- Produces: `enrich(context: dict) -> tuple[dict, dict]` where the second element is `{"ok": int, "total": int, "failed": list[str]}`
- Task 5 (jobs.py) does: `context, enrich_stats = enrich(context)` and reads `enrich_stats["ok"]`, `enrich_stats["total"]`, `enrich_stats["failed"]`.
- **Note:** `tests/test_jobs.py` mocks `enrichment.enrich` — those mocks are updated in Task 5, not here. Between Task 3 and Task 5, the existing `test_jobs.py` tests remain green because they override the real `enrich()` function with a mock.

---

- [ ] **Step 1: Update the tests to expect a tuple**

Replace the full content of `tests/enrichment/test_enrichment_init.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
import enrichment


def _noop_enrich(context):
    return context


def test_enrich_calls_all_enrichers():
    """All 5 sub-enrichers are invoked; enrich() returns (dict, stats) without raising."""
    no_op = MagicMock(side_effect=_noop_enrich)

    with (
        patch("enrichment.company_profiles.enrich", no_op),
        patch("enrichment.sector_map.enrich", no_op),
        patch("enrichment.outcome_tracker.enrich", no_op),
        patch("enrichment.masi_history.enrich", no_op),
        patch("enrichment.reddit.enrich", no_op),
    ):
        context, stats = enrichment.enrich({})

    assert isinstance(context, dict)
    assert stats == {"ok": 5, "total": 5, "failed": []}
    assert no_op.call_count == 5


def test_failing_enricher_does_not_abort_others():
    """A single failing enricher does not prevent the remaining ones from running."""
    failing = MagicMock(side_effect=Exception("boom"))
    succeeding = MagicMock(side_effect=_noop_enrich)

    # company_profiles raises; the other four must still run
    with (
        patch("enrichment.company_profiles.enrich", failing),
        patch("enrichment.sector_map.enrich", succeeding),
        patch("enrichment.outcome_tracker.enrich", succeeding),
        patch("enrichment.masi_history.enrich", succeeding),
        patch("enrichment.reddit.enrich", succeeding),
    ):
        context, stats = enrichment.enrich({})

    assert isinstance(context, dict)
    assert stats["ok"] == 4
    assert stats["total"] == 5
    assert "company_profiles" in stats["failed"]
    assert failing.call_count == 1
    assert succeeding.call_count == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/enrichment/test_enrichment_init.py -v
```

Expected: 2 FAILED (cannot unpack non-sequence dict — enrich still returns a plain dict)

- [ ] **Step 3: Update enrichment/__init__.py**

Replace the full content of `enrichment/__init__.py`:

```python
import logging

logger = logging.getLogger(__name__)


def enrich(context: dict) -> tuple[dict, dict]:
    from enrichment import (
        company_profiles,
        sector_map,
        outcome_tracker,
        masi_history,
        reddit,
    )
    enrichers = [company_profiles, sector_map, outcome_tracker, masi_history, reddit]
    failed: list[str] = []
    for enricher in enrichers:
        try:
            context = enricher.enrich(context)
        except Exception as exc:
            logger.warning(f"Enricher {enricher.__name__} failed: {exc}")
            failed.append(enricher.__name__.split(".")[-1])
    stats = {"ok": len(enrichers) - len(failed), "total": len(enrichers), "failed": failed}
    return context, stats
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/enrichment/test_enrichment_init.py -v
```

Expected: 2 PASSED

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All previously passing tests still pass. The `test_jobs.py` tests mock `enrichment.enrich` so they are unaffected by the real function's new return type.

- [ ] **Step 6: Commit**

```bash
git add enrichment/__init__.py tests/enrichment/test_enrichment_init.py
git commit -m "feat: enrich() returns (context, stats) tuple"
```

---

### Task 4: delivery/email.py — health footer param

**Files:**
- Modify: `delivery/email.py:29-31`
- Modify: `tests/test_delivery.py` (append two new test functions)

**Interfaces:**
- Consumes: nothing from previous tasks
- Produces: `send_morning_briefing(html_body: str, health_html: str | None = None) -> None`
  - When `health_html` is provided, it is inserted before `</body>`
  - Task 5 (jobs.py) calls `send_morning_briefing(html, health_html=health.to_html_footer())`

---

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_delivery.py`:

```python
def test_send_morning_briefing_appends_health_footer():
    """health_html is inserted just before </body> when provided."""
    from delivery.email import send_morning_briefing
    from unittest.mock import patch, MagicMock

    captured = {}

    def fake_send_email(subject, html_body):
        captured["body"] = html_body

    with patch("delivery.email.send_email", side_effect=fake_send_email):
        send_morning_briefing(
            "<html><body><p>Content</p></body></html>",
            health_html="<div>HEALTH</div>",
        )

    assert "<div>HEALTH</div></body>" in captured["body"]


def test_send_morning_briefing_without_health_footer():
    """html_body is unchanged when health_html is None."""
    from delivery.email import send_morning_briefing
    from unittest.mock import patch

    captured = {}

    def fake_send_email(subject, html_body):
        captured["body"] = html_body

    with patch("delivery.email.send_email", side_effect=fake_send_email):
        send_morning_briefing("<html><body><p>Content</p></body></html>")

    assert captured["body"] == "<html><body><p>Content</p></body></html>"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_delivery.py::test_send_morning_briefing_appends_health_footer \
    tests/test_delivery.py::test_send_morning_briefing_without_health_footer -v
```

Expected: 2 FAILED — `send_morning_briefing()` does not accept `health_html` keyword argument.

- [ ] **Step 3: Update delivery/email.py**

Replace lines 29–31 in `delivery/email.py`:

```python
def send_morning_briefing(html_body: str, health_html: str | None = None) -> None:
    if health_html:
        html_body = html_body.replace("</body>", f"{health_html}</body>")
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    send_email(f"BVC Morning Briefing — {date_str}", html_body)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_delivery.py -v
```

Expected: All delivery tests PASSED (5 total including the 2 new ones).

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add delivery/email.py tests/test_delivery.py
git commit -m "feat: send_morning_briefing accepts optional health footer"
```

---

### Task 5: scheduler/jobs.py — wire health collector and debug snapshot

**Files:**
- Modify: `scheduler/jobs.py` (add imports, add `_write_debug_snapshot`, rewrite `run_morning_briefing`)
- Modify: `tests/test_jobs.py` (update 4 existing `enrich` mocks to return tuples, add `get_masi_history` mock to 4 tests, add 2 new tests)

**Interfaces:**
- Consumes from Task 1: `new_run_id() -> str`, `set_run_id(str) -> None` from `observability.run_context`
- Consumes from Task 2: `RunHealthCollector` from `observability.health`
- Consumes from Task 3: `enrich(context) -> tuple[dict, dict]` — unpack as `context, enrich_stats`
- Consumes from Task 4: `send_morning_briefing(html, health_html=...)` — pass `health.to_html_footer()`
- Produces: `_write_debug_snapshot(run_id, date, failed_at, exc, context, health)` — private helper, tested directly

---

- [ ] **Step 1: Write the failing tests**

These are the 2 new tests. Append them to `tests/test_jobs.py`. They import `_write_debug_snapshot` directly and test it as a unit:

```python
# ---------------------------------------------------------------------------
# _write_debug_snapshot
# ---------------------------------------------------------------------------

class TestWriteDebugSnapshot:
    def test_creates_file_with_correct_structure(self, tmp_path, monkeypatch):
        """Snapshot JSON is written to logs/debug/ with expected top-level keys."""
        import json
        from observability.health import RunHealthCollector

        monkeypatch.setattr("scheduler.jobs.LOG_PATH", tmp_path / "logs" / "mizan.log")

        from scheduler.jobs import _write_debug_snapshot

        health = RunHealthCollector(run_id="run-0830", date="2026-06-26")
        health.stocks_collected = 5
        health.ai_ok = True

        context = {
            "bvc": {"data": {"stocks": [{"ticker": "OCP", "close": 262.0}]}},
            "news": {"data": {"articles": []}},
            "sector_map": {"Banking": {}},
        }

        _write_debug_snapshot(
            run_id="run-0830",
            date="2026-06-26",
            failed_at="email_delivery",
            exc=Exception("SMTP auth failed"),
            context=context,
            health=health,
        )

        debug_dir = tmp_path / "logs" / "debug"
        snapshots = list(debug_dir.glob("*.json"))
        assert len(snapshots) == 1

        data = json.loads(snapshots[0].read_text())
        assert data["run_id"] == "run-0830"
        assert data["failed_at"] == "email_delivery"
        assert "SMTP auth failed" in data["exception"]
        assert "traceback" in data
        assert "health" in data
        assert "context_snapshot" in data
        # sector_map must be stripped from snapshot
        assert "sector_map" not in data["context_snapshot"]

    def test_silent_fail_on_permission_error(self, tmp_path, monkeypatch, caplog):
        """If the debug dir cannot be written, a warning is logged and no exception propagates."""
        import logging
        from observability.health import RunHealthCollector

        # Point LOG_PATH to a path that cannot be created (file exists at parent location)
        bad_parent = tmp_path / "not_a_dir.txt"
        bad_parent.write_text("block")
        monkeypatch.setattr(
            "scheduler.jobs.LOG_PATH", bad_parent / "logs" / "mizan.log"
        )

        from scheduler.jobs import _write_debug_snapshot

        health = RunHealthCollector(run_id="run-0830", date="2026-06-26")

        with caplog.at_level(logging.WARNING, logger="scheduler.jobs"):
            _write_debug_snapshot(
                run_id="run-0830",
                date="2026-06-26",
                failed_at="ai_analysis",
                exc=Exception("oops"),
                context={},
                health=health,
            )

        assert any("debug snapshot" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_jobs.py::TestWriteDebugSnapshot -v
```

Expected: 2 FAILED (ImportError: cannot import name `_write_debug_snapshot`)

- [ ] **Step 3: Add imports to scheduler/jobs.py**

Change the top of `scheduler/jobs.py` from:
```python
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
```

To:
```python
import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
```

- [ ] **Step 4: Add _write_debug_snapshot to scheduler/jobs.py**

Add this function after `_load_watchlist()` (around line 29), before `collect_and_persist()`:

```python
def _write_debug_snapshot(
    run_id: str,
    date: str,
    failed_at: str,
    exc: Exception,
    context: dict,
    health: "RunHealthCollector",
) -> None:
    debug_dir = LOG_PATH.parent / "debug"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = debug_dir / f"{date}-{run_id}.json"

        _PRUNE = {"sector_map", "past_performance", "reddit_discussions"}
        pruned = {k: v for k, v in context.items() if k not in _PRUNE}
        if "bvc" in pruned:
            stocks = pruned["bvc"].get("data", {}).get("stocks", [])
            clean_stocks = [{k: v for k, v in s.items() if k != "profile"} for s in stocks]
            pruned = {
                **pruned,
                "bvc": {
                    **pruned["bvc"],
                    "data": {**pruned["bvc"].get("data", {}), "stocks": clean_stocks},
                },
            }

        snapshot = {
            "run_id": run_id,
            "date": date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failed_at": failed_at,
            "exception": str(exc),
            "traceback": traceback.format_exc(),
            "health": {
                "stocks_collected": health.stocks_collected,
                "bvc_cached": health.bvc_cached,
                "news_articles": health.news_articles,
                "enrichers_ok": health.enrichers_ok,
                "enrichers_total": health.enrichers_total,
                "ai_ok": health.ai_ok,
                "email_sent": health.email_sent,
                "warnings": health.warnings,
            },
            "context_snapshot": pruned,
        }

        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, default=str)
        logger.info(f"Debug snapshot written: {snapshot_path}")
    except Exception as snap_exc:
        logger.warning(f"Failed to write debug snapshot: {snap_exc}")
```

Also add the `RunHealthCollector` type hint import at the top of the function (using a string annotation so it's not a circular import — we use a string literal `"RunHealthCollector"` in the signature which is already there as a string annotation).

You also need the actual runtime import. Add it inside `_write_debug_snapshot` is not needed — we only use `health.` attributes there. The type hint `"RunHealthCollector"` is a string annotation and requires no import at module level. ✓

- [ ] **Step 5: Run new tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_jobs.py::TestWriteDebugSnapshot -v
```

Expected: 2 PASSED

- [ ] **Step 6: Rewrite run_morning_briefing in scheduler/jobs.py**

Replace the entire `run_morning_briefing()` function (lines 107–178 in the current file):

```python
def run_morning_briefing(dry_run: bool = False) -> None:
    from agent.analyst import run_morning_analysis
    from agent.formatter import format_morning_briefing
    from delivery.email import send_morning_briefing
    from storage.db import save_briefing, get_masi_history
    from enrichment import enrich
    from enrichment.outcome_tracker import record_picks
    from observability.run_context import new_run_id, set_run_id
    from observability.health import RunHealthCollector

    rid = new_run_id()
    set_run_id(rid)
    date_str = datetime.now(MOROCCO_TZ).date().isoformat()
    health = RunHealthCollector(run_id=rid, date=date_str)
    logger.info("Running morning briefing")

    context = collect_and_persist()
    stocks = context["bvc"]["data"].get("stocks", [])
    health.stocks_collected = len(stocks)
    health.stocks_total = len(stocks)
    health.bvc_cached = any(s.get("_cached") for s in stocks)
    health.news_articles = len(context["news"]["data"].get("articles", []))

    try:
        context, enrich_stats = enrich(context)
        health.enrichers_ok = enrich_stats["ok"]
        health.enrichers_total = enrich_stats["total"]
        health.reddit_ok = bool(context.get("reddit_discussions"))
        health.masi_rows = len(get_masi_history(days=252))
        for name in enrich_stats.get("failed", []):
            health.add_warning(f"{name} enricher failed")
    except Exception as exc:
        logger.warning(f"Enrichment pipeline failed: {exc}")
        health.add_warning(f"enrichment pipeline: {exc}")

    analysis = run_morning_analysis(context)
    health.ai_ok = "error" not in analysis

    if "error" in analysis:
        logger.warning("AI analysis unavailable; sending fallback briefing with raw data")
        raw_bvc = context.get("bvc", {}).get("data", {})
        raw_json = json.dumps(raw_bvc, indent=2, default=str)[:3000]
        html = (
            f"<html><body>"
            f"<h2>BVC Briefing — {date_str} (AI Unavailable)</h2>"
            f"<p>AI analysis could not be generated today. Raw market data below.</p>"
            f"<pre>{raw_json}</pre>"
            f"</body></html>"
        )
        save_briefing(date_str, html, context)
        _write_debug_snapshot(
            rid, date_str, "ai_analysis", Exception(analysis["error"]), context, health
        )
        if dry_run:
            print("\n" + "=" * 60)
            print("FALLBACK BRIEFING (AI unavailable — DRY RUN)")
            print("=" * 60)
            print(html[:500])
        else:
            try:
                send_morning_briefing(html)
            except Exception as exc:
                logger.error(
                    f"Fallback briefing email delivery failed: {exc}", exc_info=True
                )
        logger.info(health.to_log_line())
        return

    html = format_morning_briefing(analysis, date_str)
    save_briefing(date_str, html, context)

    try:
        record_picks(analysis, context)
    except Exception as exc:
        logger.warning(f"Failed to record picks: {exc}")
        health.add_warning(f"record_picks: {exc}")

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print("..." if len(html) > 2000 else "")
        print("\n" + health.to_log_line())
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
                logger.warning(
                    f"Morning briefing email attempt {attempt + 1} failed: {exc}"
                )
        if last_exc is not None:
            _write_debug_snapshot(
                rid, date_str, "email_delivery", last_exc, context, health
            )
            logger.error(
                f"Morning briefing email delivery failed after 2 attempts: {last_exc}",
                exc_info=True,
            )

    logger.info(health.to_log_line())
```

- [ ] **Step 7: Update existing enrich mocks in tests/test_jobs.py**

In `TestRunMorningBriefingEnrichment`, update the four tests that mock `enrichment.enrich` with a plain dict. Each of the four tests below needs two changes: (a) `return_value` becomes a tuple, (b) a `get_masi_history` mock is added.

**`test_enrich_called_after_collect`** — update the `with patch(...)` block:
```python
with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
     patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})) as mock_enrich, \
     patch("enrichment.outcome_tracker.record_picks"), \
     patch("agent.analyst.run_morning_analysis", return_value=analysis), \
     patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
     patch("storage.db.save_briefing"), \
     patch("storage.db.get_masi_history", return_value=[]), \
     patch("delivery.email.send_morning_briefing"):
```

**`test_record_picks_called_after_analysis`** — update:
```python
with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
     patch("enrichment.enrich", return_value=(enriched, {"ok": 5, "total": 5, "failed": []})), \
     patch("enrichment.outcome_tracker.record_picks") as mock_record, \
     patch("agent.analyst.run_morning_analysis", return_value=analysis), \
     patch("agent.formatter.format_morning_briefing", return_value="<html/>"), \
     patch("storage.db.save_briefing"), \
     patch("storage.db.get_masi_history", return_value=[]), \
     patch("delivery.email.send_morning_briefing"):
```

**`test_record_picks_failure_does_not_stop_briefing`** — update:
```python
with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
     patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})), \
     patch("enrichment.outcome_tracker.record_picks", side_effect=Exception("db gone")), \
     patch("agent.analyst.run_morning_analysis", return_value=analysis), \
     patch("agent.formatter.format_morning_briefing", return_value="<html/>") as mock_fmt, \
     patch("storage.db.save_briefing"), \
     patch("storage.db.get_masi_history", return_value=[]), \
     patch("delivery.email.send_morning_briefing"):
```

**`test_record_picks_not_called_on_ai_error`** — update:
```python
with patch("scheduler.jobs.collect_and_persist", return_value=ctx), \
     patch("enrichment.enrich", return_value=(ctx, {"ok": 5, "total": 5, "failed": []})), \
     patch("enrichment.outcome_tracker.record_picks") as mock_record, \
     patch("agent.analyst.run_morning_analysis", return_value={"error": "timeout"}), \
     patch("storage.db.save_briefing"), \
     patch("storage.db.get_masi_history", return_value=[]), \
     patch("delivery.email.send_morning_briefing"):
```

**`test_enrich_failure_does_not_stop_briefing`** — this test uses `side_effect=RuntimeError(...)` so `get_masi_history` won't be called (exception is caught before that line). No changes needed for this test. ✓

- [ ] **Step 8: Run the full test suite**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All tests pass including the 2 new `TestWriteDebugSnapshot` tests and all updated `TestRunMorningBriefingEnrichment` tests.

- [ ] **Step 9: Commit**

```bash
git add scheduler/jobs.py tests/test_jobs.py
git commit -m "feat: wire RunHealthCollector and debug snapshot into run_morning_briefing"
```

---

### Task 6: Makefile — log inspection targets

**Files:**
- Modify: `Makefile` (add 3 targets + update `.PHONY`)

**Interfaces:**
- Consumes: `logs/mizan.log`, `logs/errors.log`, `logs/debug/*.json` from previous tasks
- No tests needed — manual verification below

---

- [ ] **Step 1: Add three targets to Makefile**

In the `# Cleanup` section, before the `clean:` target, add:

```makefile
# ──────────────────────────────────────────────
#  Observability
# ──────────────────────────────────────────────

logs:
	tail -f logs/mizan.log

errors:
	cat logs/errors.log

debug-last:
	@latest=$$(ls -t logs/debug/*.json 2>/dev/null | head -1); \
	if [ -z "$$latest" ]; then echo "No debug snapshots found."; \
	else echo "=== $$latest ===" && $(PYTHON) -m json.tool "$$latest"; fi
```

- [ ] **Step 2: Update .PHONY**

Change the `.PHONY` line (currently ends with `check-enrichment clean`) to:

```makefile
.PHONY: install test test-coverage dry-run send-briefing alert-check-dry send-alert-check run \
        docker-build docker-up docker-logs docker-down \
        docker-dry-run docker-restart seed-history check-enrichment \
        logs errors debug-last clean
```

- [ ] **Step 3: Verify the targets are syntactically correct**

```bash
make -n logs
```

Expected: `tail -f logs/mizan.log` (dry-run output, no error)

```bash
make -n errors
```

Expected: `cat logs/errors.log`

```bash
make debug-last
```

Expected: `No debug snapshots found.` (since no failures have occurred yet)

- [ ] **Step 4: Verify a dry-run writes the log**

```bash
make dry-run 2>&1 | head -5
```

Expected: lines starting with `2026-06-26 [INFO    ] [-` (run ID shows `-` since setup_logging isn't called in dry-run? Actually `main.py` calls `setup_logging()` before `run_dry_run()`, so the log lines will use the format with `[run_id]`).

After the dry-run, check that `logs/mizan.log` was created:

```bash
ls -lh logs/mizan.log
```

Expected: file exists with non-zero size.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "feat: add logs/errors/debug-last Makefile targets"
```

---

## Self-Review

### 1. Spec Coverage

| Spec requirement | Covered by |
|---|---|
| `logs/mizan.log` INFO+ 5MB×7 | Task 1 `setup_logging()` |
| `logs/errors.log` WARNING+ 2MB×10 | Task 1 `setup_logging()` |
| `[run_id]` in every log line | Task 1 `RunIdFilter` + format string |
| Run ID format `run-HHMM` Morocco time | Task 1 `new_run_id()` |
| Thread-safe run ID via ContextVar | Task 1 `_run_id: ContextVar` |
| `RunHealthCollector` fields and methods | Task 2 |
| Health footer HTML appended to briefing email | Task 4 + Task 5 |
| `enrich()` returns stats tuple | Task 3 |
| `_write_debug_snapshot` on AI failure | Task 5 `run_morning_briefing` + `_write_debug_snapshot` |
| `_write_debug_snapshot` on email delivery failure | Task 5 `run_morning_briefing` |
| Snapshot excludes `sector_map`, `past_performance`, `reddit_discussions`, per-stock `profile` | Task 5 `_write_debug_snapshot` pruning |
| Snapshot silent-fail (warning logged) | Task 5 `_write_debug_snapshot` try/except |
| Dry-run prints log line to stdout, no email | Task 5 `run_morning_briefing` |
| `make logs`, `make errors`, `make debug-last` | Task 6 |
| No new pip dependencies | All tasks — stdlib only |
| Existing log call sites unchanged | Tasks 1–5 — all calls unchanged |

### 2. Placeholder Scan

None found.

### 3. Type Consistency

- `enrich()` return type defined in Task 3: `tuple[dict, dict]`
- Task 5 uses: `context, enrich_stats = enrich(context)` then `enrich_stats["ok"]`, `enrich_stats["total"]`, `enrich_stats["failed"]` ✓
- `RunHealthCollector` defined in Task 2 with `add_warning()`, `to_log_line()`, `to_html_footer()`
- Task 5 uses exactly these method names ✓
- `send_morning_briefing(html, health_html=...)` defined in Task 4
- Task 5 calls `send_morning_briefing(html, health_html=health.to_html_footer())` ✓
- `_write_debug_snapshot(run_id, date, failed_at, exc, context, health)` defined and tested in Task 5
- All call sites in Task 5 use this exact signature ✓
