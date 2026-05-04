# CARA developer convenience targets.
#
# Targets run from the repo root. They wrap `docker compose` and `pytest`
# with sensible defaults so a contributor (or future-you) doesn't need to
# remember which env vars matter.

CARA_TEST_BASE_URL ?= https://192.168.1.23:8455
COMPOSE = docker compose
BUILDKIT = DOCKER_BUILDKIT=0

.PHONY: help test test-smoke build-backend build-frontend up up-app down logs-backend logs-frontend smoke-curl

help:
	@echo "CARA make targets"
	@echo "  make test-smoke           Run E2E smoke tests against $(CARA_TEST_BASE_URL)"
	@echo "  make smoke-curl           Quick curl liveness check"
	@echo "  make build-backend        Build backend image (DOCKER_BUILDKIT=0 forced)"
	@echo "  make build-frontend       Build frontend image"
	@echo "  make up                   Start infra stack (postgres/redis/minio/chroma)"
	@echo "  make up-app               Start full app (infra + backend + frontend + celery)"
	@echo "  make down                 Stop everything"
	@echo "  make logs-backend         Tail backend logs"
	@echo "  make logs-frontend        Tail frontend logs"

test: test-smoke

test-smoke:
	cd backend && CARA_TEST_BASE_URL=$(CARA_TEST_BASE_URL) \
		.venv/bin/python -m pytest tests/smoke -v --tb=short

smoke-curl:
	@curl -sf -m 3 -k $(CARA_TEST_BASE_URL)/health && echo
	@curl -sf -m 3 -k $(CARA_TEST_BASE_URL)/api/v1/chat/health && echo

build-backend:
	$(BUILDKIT) $(COMPOSE) --profile app build backend

build-frontend:
	$(BUILDKIT) $(COMPOSE) --profile app build frontend

up:
	$(COMPOSE) up -d

up-app:
	$(COMPOSE) --profile app up -d

down:
	$(COMPOSE) down

logs-backend:
	docker logs -f cara-backend

logs-frontend:
	docker logs -f cara-frontend
