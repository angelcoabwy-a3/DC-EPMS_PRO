# ADR-018: Field diagnostics: battery room and MV control compartment

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator, GO for lot L5), Claude (implementation)

## Context and problem statement

Lot L5 of the operator's master specification asks for the diagnostic
work a technician does in the field: in the battery room (4 strings of
40 jars at 542.1 VDC, infrared thermography, an internal impedance
analyzer, hydrogen exhaust with an alarm at 1 % LEL) and in the control
compartment of the MV transfer lineup (PT secondary fuses F-1A / F-1B,
terminal block TB-1, a true-RMS multimeter on F-1A, P1-N1, 73-74 and the
52CC / 52TC circuits). The specification's example faults are a hot jar
(string 3, jar 18: 48.6 C, 14.2 mOhm, 10.4 V) and a blown F-1A that
starts a false emergency transfer.

## Decision drivers

- Diagnosis must be done with the instruments: the view never shows the
  fault directly (no jar ohmic value without the analyzer, no fuse
  condition without the meter).
- Inspections are not switching: measuring and scanning must not count
  as unplanned switching in the training rubric.
- Physics that a panel would challenge must be right: parallel strings
  share the bus voltage, so a shorted cell shows as string float current
  and as overcharge of the other jars, not as a string voltage drop.

## Decision

1. `backend/battery_room.py` (pure): per path 4 strings x 40 jars behind
   QF1, string disconnect SB1..SB4 with padlock, removable mid-string
   link, IR scan, analyzer reading (voltage, ohmic value against the
   jar's baseline), jar replacement only with the string open, padlocked
   and split (the string is a 542 V source by itself), lead / lag
   exhaust fans and an H2 balance. Thresholds: ohmic +30 % warn and +50 %
   replace (Battcon 2013, quoting the 30 % to 50 % band); H2 alarm 1 %
   LEL = 400 ppm (operator spec), high-high 25 % LEL = 1 % by volume
   (IFC / NFPA 1 room limit). Heating rate, 60 C runaway, float currents,
   gas evolution and ambient are model values on an accelerated time
   base. Strings off line scale the battery energy of the path.
2. `backend/mv_wiring.py` (pure): F-1A (utility sensing, also the 27
   element), F-1B (generator bus sensing), draw-out holders, a meter
   with OFF / V AC / V DC / resistance. Readings are model values
   (120 V AC PT secondary, 132 V DC station battery float). The device
   controller now uses "utility sensed" (through F-1A) for the 27
   indication, the automatic transfer and retransfer permissives, and
   "generator bus sensed" (through F-1B) before 52-GM may close.
3. Inspections (`IR_SCAN`, `MEASURE`, meter selector) are recorded as
   `inspection` events; switching stays `command`. Both go to the
   Forensic Ledger (`BATTERY_ROOM_FIELD_ACTION`, `MV_CONTROL_WIRING_ACTION`).
4. DRILL-09 (hot jar) and DRILL-10 (false start on F-1A). Field views
   `core/field_battery.js` and `core/field_wiring.js` (Layer 2, ADR-014).

## Consequences

- Real relays often supervise PT fuses (ANSI 60, loss of potential) and
  block 27; this model has no 60 element, following the specification's
  false-start scenario. Pulling F-1A on a live incomer trips 52-U.
- The 4-string room is the specification's layout, not sized to the
  10 min runtime of the 20 MW bank. IEEE 1188 was not read for this lot.
- The multimeter knows the test points of TB-1 only; it is not a free
  probe on arbitrary nodes.
