# ADR-014: Field view (Layer 2) and draw-out cubicles for 52-U / 52-GM

- Status: accepted
- Date: 2026-11-15
- Deciders: Wilmer Y. Angel Beltran (operator), Claude (implementation)

## Context and problem statement

The operator's master specification for the training simulator asks for a
second layer next to the control-room mimic: the equipment as a technician
meets it at the line-up (racking, closing springs, lockout relay, padlocks).
Until now the 13.8 kV mains 52-U and 52-GM existed only as the state of the
transfer controller (UTILITY / GENERATORS / OPEN). Two questions had to be
settled: what visual language Layer 2 uses, and where the mechanical state of
a draw-out breaker lives without creating a second source of truth.

## Decision drivers

- HMI H1 (ISA-101 style) is the operator's choice for the control room: grey
  by default, colour only for abnormal states, no decorative motion.
- The specification asks for realistic hardware (powder-coated steel,
  nameplates, Fresnel pilot lights, mechanisms).
- One source of truth for breaker position: alarms, SLD, drills and ledger
  must never disagree.
- ADR-006: no agent may import the control modules.

## Decision

1. **Visual language by layer.** Layer 1 (Power SLD) stays ISA-101. Layer 2
   (field view) draws the hardware as it looks: real equipment colours
   (red CLOSED / green OPEN flags, yellow CHARGED spring, orange arc-flash
   label header). Operator approved this split on 2026-11-15.
2. **Cubicle model in `backend/mv_cubicle.py`** (pure): racking position,
   closing spring (motor or 5 manual strokes, model values), ANSI 86 lockout,
   personal padlock, and the interlocks C1 to C8. The breaker's OPEN / CLOSED
   state in CONNECTED is NOT stored there: it stays the transfer controller's
   state. In TEST the breaker is off the bus and its test position lives in
   the cubicle.
3. **Every close path checks the cubicle**: remote transfer commands, the
   automatic transfer (which treats a non-closable 52-U as an unavailable
   normal source) and the sync-check supervised close.
4. **Field actions are "command" events named `ACTION@BREAKER`** so drills can
   list them (`procedure_commands`) or forbid them (`command_used`).
5. **Honest arc-flash label**: no study exists, the label says
   "ARC FLASH STUDY NOT PERFORMED" and shows no incident energy or boundary.

## Consequences

- Positive: one truth for breaker position; DRILL-05 (rack out and lock out
  52-GM) is checked by the server; the SLD shows TEST / DISC / 86 / LOCKED
  next to the mains; new alarms (main unavailable, 86 tripped, spring
  discharged with motor OFF).
- Negative: the drawing is SVG built once per open and patched by
  attributes; adding a new device to Layer 2 means new hooks in
  `core/field_switchgear.js`.
- Not covered: arc-flash calculation, earthing switches on the mains,
  control-power loss (CPT fuses, station battery) and relay settings. These
  belong to later lots (L2 transformer, L5 diagnostics).
