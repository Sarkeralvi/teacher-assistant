SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: test lint verify up up-infra down health ps frontend-health backend-test frontend-lint codex-ok backend-host-dev e2e e2e-headed

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

up-infra:
	$(COMPOSE) up -d postgres redis

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

health:
	curl -fsS http://localhost:8000/health

frontend-health:
	curl -fsS http://localhost:3000/health >/dev/null

frontend-repair:
	rm -rf apps/web/.next
	cd apps/web && npm run build
	$(COMPOSE) up -d --no-deps --force-recreate frontend

backend-test:
	cd apps/api && python -m pytest -q

frontend-lint:
	cd apps/web && npm run lint

codex-ok:
	codex exec --skip-git-repo-check --cd /tmp --sandbox read-only --output-last-message /tmp/ta_codex_ok.txt 'Reply with OK only.'
	cat /tmp/ta_codex_ok.txt

backend-host-dev:
	mkdir -p /tmp/teacher-assistant-host-data/uploads /tmp/teacher-assistant-host-data/artifacts
	cd apps/api && \
	APP_ENV=development \
	DATABASE_URL='postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant' \
	REDIS_URL='redis://localhost:6379/0' \
	LOCAL_STORAGE_ROOT='/tmp/teacher-assistant-host-data' \
	UPLOADS_DIR='/tmp/teacher-assistant-host-data/uploads' \
	ARTIFACTS_DIR='/tmp/teacher-assistant-host-data/artifacts' \
	BRAIN_PROVIDER=mock \
	CODEX_BROWSER_GRADING_ENABLED=true \
	CODEX_CLI_SKIP_GIT_REPO_CHECK=true \
	CODEX_CLI_COMMAND=codex \
	CODEX_CLI_SANDBOX=read-only \
	CODEX_CLI_APPROVAL_POLICY=never \
	CODEX_CLI_USE_JSON=true \
	CODEX_CLI_OUTPUT_LAST_MESSAGE=true \
	CODEX_CLI_IMAGE_INPUT_ENABLED=$${CODEX_CLI_IMAGE_INPUT_ENABLED:-false} \
	CODEX_CLI_WORKDIR='$(CURDIR)' \
	../../.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

e2e:
	docker run --rm --ipc=host --shm-size=1g --add-host=host.docker.internal:host-gateway \
		-e E2E_BASE_URL=http://host.docker.internal:3000 \
		-e E2E_API_BASE_URL=http://host.docker.internal:8000 \
		-v $(CURDIR):/work -w /work/apps/web \
		mcr.microsoft.com/playwright:v1.60.0-jammy npm run e2e

e2e-headed:
	docker run --rm --ipc=host --shm-size=1g --add-host=host.docker.internal:host-gateway \
		-e E2E_BASE_URL=http://host.docker.internal:3000 \
		-v $(CURDIR):/work -w /work/apps/web \
		mcr.microsoft.com/playwright:v1.60.0-jammy npm run e2e:headed
