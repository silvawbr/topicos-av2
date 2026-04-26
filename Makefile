VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest

.PHONY: venv install test db-up db-down db-logs db-psql db-status db-reset db-migrate-or-create db-restore-validate db-backup clean

venv:
	@if [ ! -d "$(VENV)" ]; then \
		if command -v python3.11 >/dev/null 2>&1; then \
			python3.11 -m venv $(VENV); \
		else \
			python3 -m venv $(VENV); \
		fi; \
	fi

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST)

db-up:
	./scripts/db_up.sh

db-down:
	docker compose --env-file .env down

db-logs:
	docker compose --env-file .env logs -f postgres

db-psql:
	docker exec -it $$(grep '^POSTGRES_CONTAINER_NAME=' .env | cut -d '=' -f2-) psql -U $$(grep '^POSTGRES_USER=' .env | cut -d '=' -f2-) -d $$(grep '^POSTGRES_DB=' .env | cut -d '=' -f2-)

db-status:
	docker compose --env-file .env ps

db-reset:
	docker compose --env-file .env down -v

db-migrate-or-create:
	./scripts/db_migrate_or_create.sh

db-restore-validate:
	./scripts/db_restore_validate.sh

db-backup:
	./scripts/db_backup.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
