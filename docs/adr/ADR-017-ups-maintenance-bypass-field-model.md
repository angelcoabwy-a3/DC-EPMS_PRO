# ADR-017: UPS bank system breakers and external maintenance bypass

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator, GO for lot L4), Claude (implementation)

## Context and problem statement

Lot L4 of the operator's master specification asks for the UPS front of
four make-before-break breakers (Q1 rectifier input, Q2 static-bypass
input, Q4 MIB, Q3 MBB), a Kirk-key solenoid interlock, the real sequence
to and from maintenance bypass, and the battery breaker QF1 with shunt
trip and LOTO hasp. The A3 design has a bank of 8 x 2.5 MW blocks per
path; until L4 the only UPS controls were per-block mode commands.

## Decision drivers

- The critical load must never see a break caused by the model itself;
  a break caused by an operator error must be visible and recorded.
- Vendor procedures (Toshiba G9000 MBS, Schneider Galaxy VX, Powerware
  9315 MBM) agree on the order: UPS to static bypass, key from the SKRU,
  close MBB, open MIB, lock MIB and return its key, DC breakers off,
  input breakers off. Return is the mirror image.
- One source of truth for block states (device controller) and for the
  load feed (battery logic, alarms, SLD, drills).

## Decision

1. **Bank-level system** (`backend/ups_bypass.py`, pure): one `UpsSystem`
   per path with Q1 / Q2 / Q3 / Q4 / QF1, QF1 padlock, and a two-lock key
   chain with an SKRU: two keys keyed alike, MIB unlocked and one key in
   the SKRU in normal service. The SKRU releases its key only with the
   bank on static bypass and the bypass live. This makes "MBB closed onto
   the inverter" and "MIB opened before MBB" impossible by construction;
   the model also refuses them with an explicit reason. The two-key
   reading and the Q-names are this model's; a site follows its drawing.
2. **Load feed** (`_load_feed`): maintenance bypass when Q3 is closed and
   the source is live (no battery behind it); otherwise MIB open = lost;
   blocks on static bypass need Q2; blocks on the inverter need Q1, or
   fall to the battery, which needs QF1. The battery recharges only with
   Q1 and QF1 closed. `on_battery` and `load_feed` reach the path summary,
   the ON_BATTERY alarm and the UPS status text.
3. **Consequences, not prohibitions**, for the remaining operator errors:
   Q2 opened under static bypass or Q1 with QF1 open drops the load; a
   utility loss while on maintenance bypass drops it at once.
4. **Block commands respect the system**: inverter commands refused with
   MBB closed, a key out of the SKRU or Q1 open; static bypass refused
   with Q2 open. Q1, Q2 and Q4 all open park the blocks (ISOLATED);
   closing Q2 brings them back on static bypass behind the MIB.
5. Route `POST /api/ups-systems/{path}/action`, ledger
   `UPS_SYSTEM_FIELD_ACTION`, alarms `PATH_x_UPS_*`, DRILL-08, field view
   `core/field_ups.js` (Layer 2, ADR-014).

## Consequences

- Battery strings, jar diagnostics, thermography and hydrogen are left
  to lot L5; QF1 shunt trip exists as a training injection only.
- Per-block isolation through the existing ISOLATE command keeps its
  N+1 rule; the maintenance bypass is the path for whole-bank work.
