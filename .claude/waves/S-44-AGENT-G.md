# S-44-AGENT-G — Agent Executive Manager: Frontend Surfacing

## Goal
Surface the SLOP AI Agent's executive manager role and process integrity health
dimension in the frontend. After this wave, operators can see rule-enforcement
health alongside LLM connectivity in the health dashboard.

## Context
Prior waves (S1–S4 this session) established:
- `AGENT_DISPLAY_NAME = "SLOP Agent — Executive Manager"` in `backend/core/agent.py`
- `backend/agent/integrity.py` — `run_process_integrity_check()` runs each health
  cycle, writes `subject_type="process_integrity"` health records
- `/api/v1/health/summary` already returns `process_integrity_status: str`
  (ok / degraded / critical / unknown) — see `backend/api/health.py` ~line 161
- Frontend API client (`frontend/src/api/client.ts`) does NOT yet know about
  `process_integrity_status` — no type or fetch call exists for it

## Rules to follow
- `frontend/src/views/HealthView.vue` is a grandfathered violator at ~752 lines —
  do NOT grow it. All new logic goes in a composable.
- Any new computed/ref/function belongs in `frontend/src/composables/useAgentIntegrity.ts`
  (create it).
- Hard limit: new view files ≤ 600 lines. HealthView must not grow past its current size.

## Deliverables

### 1. Backend — detail endpoint
Add `GET /api/v1/health/integrity` to `backend/api/health.py`.
Response shape:
```json
{
  "status": "ok|degraded|critical|unknown",
  "critical_gaps": 0,
  "high_gaps": 0,
  "total_rules": 76,
  "summary": "...",
  "checked_at": 1234567890
}
```
Read the most recent health record WHERE `subject_type='process_integrity'` AND
`subject_key='enforcement_coverage'`. Parse the `summary` field to extract counts
(or store them as JSON in the summary — check what `integrity.py` actually writes
and adapt accordingly). Return 200 with `status="unknown"` if no record exists yet.
Register the route in `backend/api/main.py` alongside the existing health routes.

### 2. Frontend — API client
In `frontend/src/api/client.ts`, add:
- `IntegrityStatus` type: `{ status: string; critical_gaps: number; high_gaps: number; total_rules: number; summary: string; checked_at: number }`
- `health.integrity()` fetch function calling `GET /api/v1/health/integrity`

### 3. Frontend — composable
Create `frontend/src/composables/useAgentIntegrity.ts`:
- `integrityStatus` ref (IntegrityStatus | null)
- `fetchIntegrity()` async function
- `integrityLabel` computed: "All rules covered" / "N high-risk gaps" / "N critical gaps"
- `integrityColor` computed: "text-green-600" / "text-yellow-500" / "text-red-500" / "text-slate-400"

### 4. Frontend — HealthView
In `frontend/src/views/HealthView.vue`, find the SLOP Agent section (~line 70).
Currently shows the agent check rows. Add beneath the existing agent checks:
- A single status row showing "Process Integrity" label + `integrityLabel` + colored
  status badge — matching the visual style of the existing LLM agent status row (~line 28)
- If status is degraded or critical: show `integrityStatus.summary` as a sub-line
  in muted text (one line only, truncated with ellipsis if long)
- Import and call `useAgentIntegrity` in the script section; call `fetchIntegrity()`
  alongside the existing health fetches in the onMounted/refresh block
- Do NOT add raw logic to the view — wire to the composable only

### 5. Tests
- Add a test to `tests/test_agent_integrity.py` covering the new
  `GET /api/v1/health/integrity` endpoint (use TestClient, assert shape)
- TypeScript: run `npm --prefix frontend run type-check` — must pass clean

## Verification
Run in order:
1. `.venv/bin/pytest tests/test_agent_integrity.py -v` — all pass
2. `python3 ms-enforce` — exit 0
3. `npm --prefix frontend run type-check` — no errors
4. Start dev server and visually confirm the integrity status row appears in the
   Agent section of the health dashboard
