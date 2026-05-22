# Mediastack developer commands
# Run any target with: make <target>

.PHONY: test test-contracts test-fast test-full lint check deploy-check

# ── Testing ───────────────────────────────────────────────────────────────

## Run the full pytest suite (excluding slow integration tests)
test:
	pytest tests/ -q --tb=short --ignore=tests/test_integration.py

## Run only wizard contract tests (5 seconds — catches integration gaps)
test-contracts:
	@echo "=== Wizard Contract Tests ==="
	pytest tests/test_wizard_contracts.py -v
	@echo ""
	@echo "=== Static Contract Analysis ==="
	python3 tools/analyze-tests.py --contracts

## Fast pre-commit checks (contracts + shell scripts + DB sanity)
test-fast:
	pytest tests/test_wizard_contracts.py -q --tb=short
	python3 tools/analyze-tests.py --contracts
	python3 ms-test.py --section A,I,J,P

## Full test run including ms-test against live server
test-full:
	pytest tests/ -q --tb=short --ignore=tests/test_integration.py
	python3 ms-test.py

## Analyze existing pytest suite for quality gaps
analyze:
	python3 ms-test.py --analyze-tests

## Show test trend from history
trend:
	python3 ms-test.py --trend

# ── Code quality ─────────────────────────────────────────────────────────

## Check Python syntax on all backend files
lint:
	python3 -m py_compile backend/**/*.py
	@echo "Syntax OK"

## Build frontend and check bundle size
build:
	cd frontend && npm run build

## Full pre-deploy check: contracts + tests + frontend build
check: test-contracts test build
	@echo ""
	@echo "✓ All checks passed — safe to deploy"

# ── Server operations ────────────────────────────────────────────────────

## Run ms-test sections P and Q against live server (wizard contracts + invariants)
live-check:
	python3 ms-test.py --section P,Q

## Full live server test
live-test:
	python3 ms-test.py

# ── Update shortcuts ──────────────────────────────────────────────────────

## Full update + all test scripts immediately (no prompts)
full-update:
	sudo ms-update --full

## Run test scripts only (no update/restart) — safe to run anytime
tests-only:
	sudo ms-update --tests

# ── Install (alias for setup) ─────────────────────────────────────────────
install: check
	@echo 'Mediastack dependencies installed. Run: sudo ms-update'

dev: test-fast
	@echo 'Dev checks passed.'

deploy: check live-check
	@echo 'Deploy checks passed.'

# ── Full audit ────────────────────────────────────────────────────────────

## Run the full contract audit (static + live tests)
audit:
	python3 ms-audit

## Run audit static analysis only (no server needed)
audit-static:
	python3 ms-audit --static

## Run audit and generate AI tests for gaps (requires ANTHROPIC_API_KEY)
audit-improve:
	python3 ms-audit --improve

## Apply AI-generated tests immediately
audit-apply:
	python3 ms-audit --improve --apply

## Show audit history
audit-history:
	python3 ms-audit --summary

## Run audit and save detailed markdown report
audit-report:
	python3 ms-audit --report

# ── FSM Tests ─────────────────────────────────────────────────────────────────
.PHONY: test-fsm test-fsm-install test-fsm-platform test-all

test-fsm: test-fsm-install test-fsm-platform test-fsm-health
	@echo "FSM tests complete"

test-fsm-install:
	@echo "── App Install FSM ──────────────────────"
	$(PYTHON) -m pytest tests/test_fsm_app_install.py -v --tb=short

test-fsm-platform:
	@echo "── Platform FSM ─────────────────────────"
	$(PYTHON) -m pytest tests/test_fsm_platform.py -v --tb=short

test-all: test coverage
	@echo "── Full Framework ───────────────────────"
	./ms-test-all

coverage:
	./ms-coverage

gaps:
	./ms-coverage --gaps

gen:
	./ms-testgen

gen-all:
	./ms-testgen --force

audit:
	./ms-audit

audit-improve:
	./ms-audit --improve

test-fsm-health:
	@echo "── Health Check FSM ─────────────────────"
	$(PYTHON) -m pytest tests/test_fsm_health_check.py -v --tb=short
