# ADR-019: Disturbance recorder and oscillography (synthesised waveforms)

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator, GO for lot L6), Claude (implementation)

## Context and problem statement

Lot L6 of the operator's master specification asks for a live
three-phase voltage viewer (VA, VB, VC at 120 degrees) that shows voltage
sags, harmonic distortion during an IGBT fault and the switching
transient (< 4 ms), plus COMTRADE. The plant is a supervisory state model
(device states, breakers, sources); it has no electromagnetic or
load-flow solver, so no waveform exists to sample.

## Decision drivers

- A record must agree with what the plant did (source, UPS mode, load
  feed) and be reproducible in tests.
- Measurements must use a published definition, not an invented one.
- The exported file must open in standard COMTRADE readers.

## Decision

1. `backend/oscillography.py` (pure) SYNTHESISES each record from the
   state before and after a change and the kind of transition: bus
   collapse (time constant 8 ms, model), source appearing, open-transition
   dead time (100 ms, model), static-switch notch (3 ms, model, inside the
   specification's < 4 ms), phase step on a closed transition, utility sag
   (training injection), inverter-fault harmonics (5th 9 %, 7th 6 %,
   11th 3 %, model; THD about 11 %). Two points per path: the 13.8 kV MV
   bus and the 480 V critical load bus, phase-to-neutral, 32 samples per
   cycle, 0.1 s pre-trigger and 0.3 s post-trigger.
2. The device controller watches a per-path signature (MV source, load
   feed, MV frequency) at the end of each advance; a change takes a
   record with its cause (first plant events since the previous record).
   A manual trigger and a training sag (0.1-0.9 pu, 0.5-30 cycles, no 52-U
   trip: model reading that the sag is shorter than the 27 delay) also
   take records. 24 records are kept in memory; a reset clears them.
3. Measurements: half-cycle RMS sliding by half a cycle, minimum of the
   three phases, time below 0.9 pu, classified with IEEE 1159-2009 Table 2
   (sag 0.1-0.9 pu, interruption < 0.1 pu, instantaneous / momentary /
   temporary by duration); THD by a one-cycle DFT, harmonics 2-13.
4. COMTRADE C37.111-1999 ASCII (.cfg + .dat): 13-field analog channel
   lines, 16-bit integer scaling, UTC times (the 1999 revision has no time
   zone field).
5. Routes `GET /api/oscillography/records`, `/records/{id}`,
   `/records/{id}/comtrade?part=cfg|dat`, `POST /api/oscillography/{path}/trigger`
   and `/sag`; ledger action `DISTURBANCE_RECORDER_ACTION`. Field view
   `core/field_scope.js` (LIVE triggered display with a sweeping beam at
   the display frame rate, slow-motion replay, zoom on the trigger).

## Consequences

- Waveforms are illustrations of the plant's state changes, not
  measurements: no motor back-EMF, no fault current, no transformer
  inrush, no real switching time. The view and the files say so.
- A 3 ms notch reads as a short sag of about 0.8 pu over one half-cycle
  RMS window: that is how an RMS-based classifier sees it.
- The COMTRADE output was checked against the field layout only; it was
  not opened in a vendor COMTRADE viewer.
