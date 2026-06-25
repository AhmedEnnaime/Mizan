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

clean:
	find . -type d -name __pycache__ | grep -v .venv | xargs rm -rf
	find . -name "*.pyc" | grep -v .venv | xargs rm -f
	rm -rf .pytest_cache

.PHONY: install test test-coverage dry-run run \
        docker-build docker-up docker-logs docker-down \
        docker-dry-run docker-restart clean
