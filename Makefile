SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: test lint verify up down health ps frontend-health backend-test frontend-lint

test:
	cd apps/api && python -m pytest -q

lint:
	cd apps/api && python -m ruff check .
	cd apps/web && npm run lint

verify:
	$(MAKE) health
	$(MAKE) frontend-health
	$(MAKE) test
	$(MAKE) lint

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

health:
	curl -fsS http://localhost:8000/health

frontend-health:
	curl -fsS http://localhost:3000 >/dev/null

backend-test:
	cd apps/api && python -m pytest -q

frontend-lint:
	cd apps/web && npm run lint
