# DONE: Health Check FSM Implemented

See: tests/test_fsm_health_check.py (23 tests)
FakeDockerClient: tests/conftest.py (FakeContainer, FakeDockerClient, fake_docker fixture)

---

# TODO: Health Check FSM Tests

## Status: Deferred (next sprint)

## Why Deferred
10 check types × 3 states × multiple apps = 30+ combinations minimum.
Tests require a running Docker environment with controllable container health.
The install and platform FSMs (now implemented) have produced the most bugs historically.

## FSM Definition

### States (per check, per app):
- `ok`       — check passed
- `warning`  — degraded but functional
- `error`    — check failed, fix may be available
- `unknown`  — check not yet run

### Transitions:
- T1 `unknown` → `ok`       health cycle runs, container healthy
- T2 `unknown` → `error`    health cycle runs, container unreachable
- T3 `ok`      → `warning`  degradation detected (disk filling, slow response)
- T4 `ok`      → `error`    container crashes or port closes
- T5 `warning`  → `ok`      issue self-resolved
- T6 `warning`  → `error`   degradation becomes failure
- T7 `error`   → `ok`       fix applied (manual or auto), health recovers
- T8 `error`   → `warning`  partial recovery

### Guards:
- G1 Health cycle only runs for apps with status='running'
- G2 Pending fixes suppressed if same fix rejected 3× (suppression)
- G3 Auto-fix only executes if within AI safety tier threshold
- G4 Anomaly detection only fires after 5+ history points

### Invariants:
- I1 Every error check has a human-readable summary
- I2 Suppressed fixes never auto-execute
- I3 Health history bounded (≤500 rows per check per app)
- I4 A single health cycle never produces duplicate check records for the same app+check

## Suggested Test File: tests/test_fsm_health_check.py

### TestT1T2HealthCycleInitial — first cycle sets state from unknown
### TestT3T4DegradationPath — warning and error transitions
### TestT7RecoveryPath — error → ok via fix or recovery
### TestHealthGuards — suppression, safety tiers, anomaly threshold
### TestHealthInvariants — history bounds, no duplicates, summaries exist
### TestHealthReachability — all 4 states reachable via real scheduler calls

## Prerequisite
Needs a Docker-socket-accessible test environment or a comprehensive
docker_client mock that simulates container health state changes over time.
Consider adding a `--live` marker for tests that need real Docker:
  pytest tests/test_fsm_health_check.py -m live
