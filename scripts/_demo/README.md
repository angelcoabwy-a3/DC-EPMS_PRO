# Demo state snapshots

Reproducible PostgreSQL seed for replaying recorded demo walkthroughs.

## What's in here

| File | Captured | Contents |
|---|---|---|
| `postgres_demo_state_2026-05-09.sql` | 2026-05-09 ~20:30 UTC | 91 assets + 9 work orders. Snapshot taken right after the CO+I-style demo arc closed: three predictive_kalman P1 LOTO WOs across cooling / UPS / power distribution, all CET-signed. |

## The demo arc captured

Three predictive_kalman P1 work orders — one per critical subsystem — all auto-generated from synthetic Kalman z-score excursions, all approved within an 11-minute window:

| Subsystem | Asset | WO | Channel | Kalman z | Last emission | Standard reference |
|---|---|---|---|---|---|---|
| Power Distribution | rpp_a_01 (Schneider, 2N) | `WO-20260509-f310fb57` | `thd_i_pct` | 12.8 | 18.4 % | IEEE 519-2014 §5.1 |
| Cooling | chiller_1 (York YZ, 1500 ton) | `WO-20260509-e492064a` | `chiller_LWT_c` | 18.42 | 14.7 °C | ASHRAE 6–8 °C setpoint |
| UPS / Battery | ups_a (Schneider Galaxy VX) | `WO-20260509-802dc8f0` | `batt_runtime_min` | 21.96 | 5.0 min | NEC 460.6 (capacitor) |

Plus 3 manual / incident / voice-closure follow-up WOs and 3 rejected probe artifacts in the audit history.

## After replay: 4 fresh pending WOs (post-`replay_demo.ps1`)

The replay script wipes work_orders, restores the snapshot, drops the rejected probe artifacts and the historical predictive approvals, then injects 4 fresh `pending_approval` rows so the Maintenance view starts every demo with a known baseline:

| Asset | Trigger | LOR / Pri | LOTO | MOP linked? | Demo purpose |
|---|---|---|---|---|---|
| `rpp_a_01` | predictive_kalman | 20 / **P1** | YES | yes | Act 2 demo killer 1 — THDi excursion |
| `cdu_a_01` | predictive_kalman | 20 / **P1** | YES | yes | Act 2 demo killer 2 — DLC flow drift |
| `genset_a_01` | predictive_kalman | 20 / **P1** | YES | yes | Act 2 demo killer 3 — oil pressure drop |
| `genset_b_01` | manual (shift handover) | 12 / P2 | YES | **NO** | **Act 3 Multi-Agent VETO target** — Safety Officer fires HARD STOP |

The 4th row exists so the operator can demo the Safety Officer veto without ever leaving the browser: copy the WO id from the Maintenance grid → paste into the Multi-Agent `work_order_id` input → Consult → consensus banner flips to red `HARD STOP` with the blinking VETO chip. Per ADR-006 narrative.

## Replay

Same db, idempotent (every INSERT carries `ON CONFLICT DO NOTHING`):

```powershell
docker exec -i epms-db psql -U epms -d dcepms `
  < scripts/_demo/postgres_demo_state_2026-05-09.sql
```

After replay, the Maintenance view at `http://127.0.0.1:8080/#maintenance`
should render 6 open WOs (all approved) plus the rejected pool. Verify
via `GET /api/cmms/work-orders?only_open=true&limit=200`.

## Caveats worth knowing before replay

- **Live `assets` table contains the production seed `vendor=null/model=null`.** The temporary enrichment of `ups_a` with Schneider Electric / GVX750-N480 / SVX-2024-008812 (used during the nameplate-matcher smoke test on 2026-05-09 ~18:40 UTC) was reverted before this snapshot. If you re-enrich for nameplate demos, do it after replay, not before.
- **`WO-20260509-ae9780ad.approved_by_cet = 'second.cet'`** is the residue of a re-approve audit-trail finding (re-approving an already-approved WO silently overwrites `approved_by_cet`; expected behavior is HTTP 409 or original-approver preservation). Untracked bug. Snapshot captures the post-second-approval state.
- The dump is **data-only** — schema must already exist in the target database. The schema is created by `backend/migrations/2026_05_W2_cmms_core.sql` during normal lifespan startup.

## Replay on a fresh database

If `epms-db` was wiped:

```powershell
# 1. Bring up postgres + apply schema (lifespan does this automatically on uvicorn start)
docker compose up -d epms-db
.\.venv\Scripts\Activate.ps1
$env:PG_USER='epms'; $env:PG_PASSWORD='epms_dev_only_change_me'; $env:PG_DB='dcepms'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080
# (wait for "lifespan complete" in the log, then Ctrl+C)

# 2. Replay the demo seed
docker exec -i epms-db psql -U epms -d dcepms `
  < scripts/_demo/postgres_demo_state_2026-05-09.sql

# 3. Restart uvicorn for the demo
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8080
```
