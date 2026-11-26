# ADR-015: Utility transformer field model (52-T, key chain, DETC, thermal)

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator, GO for lot L2), Claude (implementation)

## Context and problem statement

Lot L2 of the operator's master specification asks for the utility
transformer of each path (25 MVA, 27.5 kV delta / 13.8 kV wye-grounded)
as a field device: a five-position de-energized tap changer (DETC) under
a Kirk key, a live thermal model with ONAF fan stages, the marshalling-box
instruments, and protection 63 / 87T / 86T that removes the transformer
when the DETC is moved energized. Until L2 the transformer was only a
passthrough node: the plant had no device between the utility and 52-U,
so it could not be de-energized by an operator, and a DETC interlock had
nothing to interlock against.

## Decision drivers

- IEEE C57.131 scope: a DETC may be operated only while the transformer is
  not energized. The model must make that physical, not a pop-up.
- One source of truth: 52-U stays the transfer controller's state (L1).
- Honesty about numbers: no test report or nameplate exists for this
  simulated unit.
- ADR-006 fence: no agent imports the control modules.

## Decision

1. **Primary device 52-T.** A 27.5 kV primary circuit switcher is added
   per path. It is a design assumption of this model; the operator's
   design documents do not define the primary device. Opening it under
   load drops the 13.8 kV incomer: 52-U trips on 27 and the automatic
   transfer proceeds as for a utility loss.
2. **Trapped-key chain K1 / K2.** K1 lives in the 52-U lock (52-U free).
   Locking 52-U open frees K1; K1 at the 52-T lock, with 52-T open, locks
   52-T open and frees K2; K2 unlocks the DETC handle and stays trapped
   until the handle is locked on a detent. Every 52-U close path (local,
   remote, automatic) refuses while K1 is out. The chain order is the
   model's; a real site follows its own key-interlock drawing.
3. **Defeat only as an injected hazard.** A spare DETC key exists only
   when a drill or instructor injects it. Moving the handle energized is
   an internal arc: 63 and 87T operate, 86T trips 52-T and 52-U, and the
   transformer is declared damaged (re-energizing needs tests that are not
   simulated). The rubric counts the spare key as unplanned switching.
4. **Thermal model.** IEEE C57.91 Clause 7 form (exponential top-oil rise,
   hot-spot gradient as a power of load) with TYPICAL constants: 15/20/25
   MVA ONAN/ONAF1/ONAF2, 55 C top-oil rise and 80 C hot-spot rise at
   rating, exponents n 0.8/0.9, m 0.8, R 4.5. The exponents were not
   checked against the standard text. Thermal time runs x60 and the panel
   says so. Oil alarm/trip 85/95 C follow the master specification; winding
   110/130 C and fan setpoints are model values. Liquid level and nitrogen
   pressure are illustrative gauges.
5. **State lives in `backend/mv_xfmr.py`** (pure, like `mv_cubicle.py`),
   owned by the device controller and exposed in the transfer controller
   snapshot as `transformer`. No new device kind: the roster counts and the
   Power Controls panels are unchanged.
6. **Layer 2 look** as ADR-014. The SLD (Layer 1) shows only the DETC
   position, 52-T OPEN and 86T, and draws the transformer dead when it is.

## Consequences

- `_incomer_live(path)` = utility present AND transformer energized now
  drives every 52-U decision that used `utility_ok`. `utility_ok` keeps
  its meaning (grid side) for the 27 alarm and the training injections.
- The 87T relay chip on the SLD becomes live (internal-fault case only).
- With the 2N design share each path loads its transformer to about 11
  MVA, so a thermal trip is not reachable in normal operation; it is
  covered by unit tests, not by a drill.
- Not done: N2 purge valve action, a real nameplate or heat-run data,
  load tap changer (this is a DETC only), DGA.
