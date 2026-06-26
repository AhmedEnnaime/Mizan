PYTHON = .venv/bin/python
PIP    = .venv/bin/pip

# ──────────────────────────────────────────────
#  Setup
# ──────────────────────────────────────────────

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# ──────────────────────────────────────────────
#  Testing
# ──────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -v

test-coverage:
	$(PYTHON) -m pytest tests/ -v --tb=short -q

# ──────────────────────────────────────────────
#  Running the agent locally
# ──────────────────────────────────────────────

dry-run:
	$(PYTHON) main.py --dry-run

send-briefing:
	$(PYTHON) -c "from scheduler.jobs import run_morning_briefing; run_morning_briefing(dry_run=False)"

alert-check-dry:
	$(PYTHON) -c "from scheduler.jobs import run_alert_check; run_alert_check(dry_run=True)"

send-alert-check:
	$(PYTHON) -c "from scheduler.jobs import run_alert_check; run_alert_check(dry_run=False)"

run:
	$(PYTHON) main.py

# ──────────────────────────────────────────────
#  Docker
# ──────────────────────────────────────────────

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-logs:
	docker compose logs -f bvc-agent

docker-down:
	docker compose down

docker-dry-run:
	docker compose run --rm bvc-agent python main.py --dry-run

docker-restart:
	docker compose restart bvc-agent

# ──────────────────────────────────────────────
#  Cleanup
# ──────────────────────────────────────────────

seed-history:
	$(PYTHON) scripts/seed_history.py

check-enrichment:
	$(PYTHON) -c "\
import storage.db as db; \
masi = db.get_masi_history(days=5); \
picks = db.get_recent_ai_picks(days=7); \
print('=== MASI last 5 days ==='); \
[print(r) for r in masi]; \
print(); \
print('=== Recent AI picks ==='); \
[print(p) for p in picks]"

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

clean:
	find . -type d -name __pycache__ | grep -v .venv | xargs rm -rf
	find . -name "*.pyc" | grep -v .venv | xargs rm -f
	rm -rf .pytest_cache

.PHONY: install test test-coverage dry-run send-briefing alert-check-dry send-alert-check run \
        docker-build docker-up docker-logs docker-down \
        docker-dry-run docker-restart seed-history check-enrichment \
        logs errors debug-last clean
