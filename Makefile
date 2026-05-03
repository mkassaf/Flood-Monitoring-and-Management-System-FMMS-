# FMMS — common commands
# `make help` to list available targets.

.DEFAULT_GOAL := help

COMPOSE := docker compose
PYTHON_SERVICES := sensor-simulator ingestion-gateway telemetry-service rule-engine alert-service geo-service auth-service dashboard-bff
SVC ?= rule-engine

# ─── lifecycle ────────────────────────────────────────────────────

.PHONY: up
up: ## bring up infra only (broker, DBs, observability)
	$(COMPOSE) --profile infra up -d
	@echo "Infra is up. Run 'make up-all' to start application services."

.PHONY: up-all
up-all: ## bring up infra + application services
	$(COMPOSE) --profile infra --profile app up -d --build

.PHONY: down
down: ## stop everything (volumes preserved)
	$(COMPOSE) --profile infra --profile app --profile demo down

.PHONY: clean
clean: ## stop and remove volumes (DESTRUCTIVE)
	$(COMPOSE) --profile infra --profile app --profile demo down -v

.PHONY: restart
restart: down up-all ## restart the full stack

.PHONY: logs
logs: ## tail logs from all services
	$(COMPOSE) logs -f --tail=100

.PHONY: logs-svc
logs-svc: ## tail logs from one service: make logs-svc SVC=rule-engine
	$(COMPOSE) logs -f --tail=200 $(SVC)

# ─── shells ───────────────────────────────────────────────────────

.PHONY: psql
psql: ## open a psql shell to the operational DB
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-fmms} -d fmms

.PHONY: redis-cli
redis-cli: ## open a redis-cli shell
	$(COMPOSE) exec redis redis-cli

.PHONY: shell
shell: ## open a shell inside a service: make shell SVC=rule-engine
	$(COMPOSE) exec $(SVC) /bin/sh

# ─── kafka helpers ────────────────────────────────────────────────

.PHONY: topics
topics: ## list Kafka topics
	$(COMPOSE) exec redpanda rpk topic list

.PHONY: consume
consume: ## consume from a topic: make consume TOPIC=alerts.threshold
	$(COMPOSE) exec redpanda rpk topic consume $(TOPIC)

# ─── tests ────────────────────────────────────────────────────────

.PHONY: test
test: ## run all tests across all Python services
	@for svc in $(PYTHON_SERVICES); do \
		echo "── testing $$svc ──"; \
		(cd services/$$svc && python -m pytest -q) || exit 1; \
	done

.PHONY: test-svc
test-svc: ## run tests for one service: make test-svc SVC=rule-engine
	cd services/$(SVC) && python -m pytest -v

# ─── lint / format ────────────────────────────────────────────────

.PHONY: lint
lint: ## ruff + mypy across all Python services
	@for svc in $(PYTHON_SERVICES); do \
		echo "── linting $$svc ──"; \
		(cd services/$$svc && ruff check . && mypy --strict src/) || exit 1; \
	done

.PHONY: fmt
fmt: ## apply ruff format across all Python services
	@for svc in $(PYTHON_SERVICES); do \
		(cd services/$$svc && ruff format .); \
	done

# ─── load + energy ────────────────────────────────────────────────

.PHONY: load-test
load-test: ## run the locust scenario (QAS-03 / QAS-04 evidence)
	cd tools/load && locust -f locustfile.py --headless -u 200 -r 50 -t 5m

.PHONY: energy-report
energy-report: ## summarize CodeCarbon emissions logs from last run
	python tools/energy/summarize.py

# ─── demo flows ───────────────────────────────────────────────────

.PHONY: demo-case-1
demo-case-1: ## simulate Phase 0 Case 1 (threshold breach)
	$(COMPOSE) --profile demo run --rm sensor-simulator python -m sensor_simulator.demos case_1

.PHONY: demo-case-2
demo-case-2: ## simulate Phase 0 Case 2 (multi-region storm)
	$(COMPOSE) --profile demo run --rm sensor-simulator python -m sensor_simulator.demos case_2

.PHONY: demo-case-3
demo-case-3: ## simulate Phase 0 Case 3 (malfunction + redundancy)
	$(COMPOSE) --profile demo run --rm sensor-simulator python -m sensor_simulator.demos case_3

# ─── help ─────────────────────────────────────────────────────────

.PHONY: help
help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
