# Probe Registry — schema + OPEN-SEAM append contract (BATCH-11 S1, P0)

> **This document is the CONTRACT for `tools/probe_registry.json`.** Read it
> before appending a probe row. The aging engine (`tools/audit_probe_aging.py`)
> reads the registry and ages every row; you append a row, you do **not** edit
> the engine's logic. This is the general form of the Reuse-and-blast-radius
> "open seam" obligation (CLAUDE.md): a registry, not a hardcode.

## Why this exists

The Coverage+Handoff audit (§4g) named THE class: the **"GROUND-gate brownout."**
A GROUND probe that degrades to `INDETERMINATE` / unparseable / missing-input /
no-date **keeps returning the same color as a match** — the absence-of-ground
path is indistinguishable from the match path, so a gate silently browns out to
"not red." No single gate treated **sustained INDETERMINATE** as a defect.

The aging engine closes the class for ALL probes at once: it records per run
whether each registered probe **reached ground** (`verified`/`DRIFT`) or
**browned out**, and a probe with **no ground-touch in N consecutive runs**
(default N=5) ages to **DRIFT** — red, not green.

## Pinned vocabulary (CLAUDE.md "Knowledge-Lifecycle & reconciliation")

Used verbatim — do not coin synonyms:

- **GROUND** — the probe touches physics (a socket, the filesystem, `git
  rev-parse`, process env). May assert `verified` or `DRIFT`.
- **XREF** — text-vs-text. May only flag `INCONSISTENT`, never `verified`.
- **INDETERMINATE** — ground truth was unreachable; emitted LOUDLY, never
  silently downgraded to `OK`.
- **UNPROBED** — no probe exists for a fact yet; ratchets down, never up.

## The registry row SCHEMA

`tools/probe_registry.json` holds `{"probes": [ <row>, ... ]}`. Each `<row>`:

| Field | Required | Meaning |
|---|---|---|
| `id` | **yes** | Unique stable probe id (the baseline keys on it). |
| `physics` | yes | One line: **what physical ground truth** this probe touches (the socket / file / git ref / process env). If you cannot name the physics, it is XREF, not GROUND — do not register it as a ground probe. |
| `cmd` | **yes** | Shell command run from the repo root. Its stdout+stderr is classified. |
| `ground_tokens` | yes | Substrings whose presence in the output means **the probe reached ground this run** (e.g. `verified`, `DRIFT`, a bound value, `OK:` when `OK` means "read the source and reconciled"). |
| `brownout_tokens` | yes | Substrings meaning **the probe did NOT reach ground** (`INDETERMINATE`, `unparseable`, `skip`, `dateless`, `unreachable`). |
| `host_configured` | yes | `false` = no host is configured for this probe (a headless/dev context); `true` = a host IS configured and the probe SHOULD be installed there. **This is the rc127 discriminator** (see below). |
| `wrong_target` | optional | `{"json_field": "<field>", "wrong_values": [...]}` — for probes that emit JSON: if `<field>` carries a known-WRONG value, the run is a **WRONG-PHYSICS brownout** (LR-2 class), not a pass. |
| `note` | optional | Free text — rationale, known limitations, source-fix references. |

### Classification (what the engine does with a row, each run)

1. **WRONG-target** (`wrong_target` spec matches) → brownout subclass `wrong-target` → **immediate DRIFT** (the probe is lying about physics).
2. **rc == 127** ("command not found"):
   - `host_configured: true` → subclass `configured-rc127` → **immediate DRIFT** (should be installed — the LR-2 install-miss).
   - `host_configured: false` → subclass `no-host` → **quiet** (don't cry wolf in a headless context).
3. Output contains a **ground token** → `GROUND-TOUCH` (streak resets to 0).
4. Output contains a **brownout token** (no ground token) → brownout subclass `indeterminate`.
5. Neither token present → brownout subclass `unparseable` (NOT a silent pass).

### The aging rule (PINNED — consumed by all streams)

> **A probe with NO ground-touch in N consecutive runs (default N=5) → DRIFT.**

`INDETERMINATE` is **red-eligible after N runs**. A single brownout is not red
(transient unreachability is normal); *sustained* brownout is the defect. The
per-probe brownout streak lives in `.probe-health-baseline.json`; a ground-touch
resets it to 0. Plus two immediate-DRIFT shortcuts: `configured-rc127` and
`wrong-target` (above) do not wait N runs.

### configured-host rc127 vs no-host-configured (the cry-wolf discriminator)

The single most important honesty knob. **Setting `host_configured`:**

- `true` — a host is configured and the probe must be installed there. If it
  returns rc127, that is the LR-2 defect (`slop-reality-probe` never installed)
  → **DRIFT**, fix it.
- `false` — no host is configured (a dev box, CI, a headless run). rc127 is
  expected → **quiet**. Do not register a host probe as `host_configured: true`
  unless a host genuinely exists for it.

## OPEN-SEAM append mechanism — how a Phase-2 stream registers its probe

**You append a JSON object to the `probes` list in `tools/probe_registry.json`.
You do NOT edit `tools/audit_probe_aging.py`.** That is the entire contract.

Recipe (S2 per-ring reachability, S4 hook-config, future streams):

1. Open `tools/probe_registry.json`.
2. Append one row to `"probes"` filling the schema above. Pick a unique `id`.
3. Name the `physics` honestly. If there is no physics, it is XREF — do not add it.
4. Set `host_configured` correctly (the cry-wolf knob).
5. Choose `ground_tokens`/`brownout_tokens` that match your probe's ACTUAL
   output (run your `cmd` and read what it prints).
6. Run `python3 tools/audit_probe_aging.py` and confirm your row classifies the
   way you intend (GROUND-TOUCH on a healthy run).

That is it — the engine picks the row up automatically; no logic change, no
import, no registration call. Keep-both-whole-block merge applies (append your
object; never reformat neighbouring rows).

### Worked examples for the named Phase-2 consumers

- **S2 (per-ring reachability)** — one row per repo ring:
  ```json
  {
    "id": "ring_reachability_slop_process",
    "physics": "git rev-parse / filesystem stat of /home/stack/v5 docs/TODO.md",
    "cmd": "test -f /home/stack/v5/docs/TODO.md && echo verified || echo INDETERMINATE",
    "ground_tokens": ["verified"],
    "brownout_tokens": ["INDETERMINATE"],
    "host_configured": false,
    "note": "S2: registered-but-absent ring -> INDETERMINATE (caught here by aging)."
  }
  ```
- **S4 (Stop-hook present + firing)** — so the session-boundary hook can't
  silently disarm (else it's the next F7):
  ```json
  {
    "id": "session_winddown_hook_present",
    "physics": "filesystem read of .claude/settings.json hooks config",
    "cmd": "python3 -c \"import json,sys; c=json.load(open('.claude/settings.json')); print('verified' if c.get('hooks',{}).get('Stop') else 'DRIFT')\"",
    "ground_tokens": ["verified", "DRIFT"],
    "brownout_tokens": ["INDETERMINATE"],
    "host_configured": false,
    "note": "S4: the Stop hook is config, not a boundary — register it so a removed hook ages red."
  }
  ```

## The baseline ratchet

`.probe-health-baseline.json` (sibling to `.factprobe-baseline.json`):

- **Missing baseline = "establish, don't alarm"** — the first run writes it.
- Per-probe `brownout_streak` accrues run-over-run (run with `--record`).
- `aged_count` (number of currently-DRIFT probes) is **shrink-only**: it may
  decrease freely; a growing aged count emits a `WARNING`. Shrink it with
  `--update-shrunk`.
- The baseline is **stored state, reconciled against the live run every
  invocation** — never trusted blind (the K-L rule).

## ms-enforce registration

`check_probe_aging` is a **TIER_1 warn-only** check (non-hook trigger — does NOT
depend on S4's session hooks). It runs the engine in `--record` mode and surfaces
GROUND-TOUCH / BROWNOUT / DRIFT / ratchet-WARNING. **It does not auto-promote to
blocking** — promotion is a later deliberate recorded act (the Enforcement-
Lifecycle promotion trigger: clean N runs + UNPROBED ratchet at/near zero).
