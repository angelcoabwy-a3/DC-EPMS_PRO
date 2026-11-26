# ADR-020: AI training instructor (debrief) on Meta Muse Spark

- Status: accepted
- Date: 2026-11-26
- Deciders: Wilmer Y. Angel Beltran (operator: provider Meta Muse, debrief
  only, cap as recommended), Claude (implementation)

## Context and problem statement

The training drills (T1-T4, L1-L5) produce a deterministic report:
outcome, score, steps, violations, reverted steps, sequence of events and
the drill's references. Trainees asked for an instructor that explains
the attempt. The operator chose the Meta API (Muse), already used by the
hackathon features (MOP Verification, Shift Forensic Investigator) and
covered by the operator's Meta credits.

## Decision drivers

- ADR-006: no AI write authority; the plant and the rubric stay
  deterministic.
- Cost must be bounded without knowing the per-token price.
- The feature must work without a key (public host, tests).

## Decision

1. `backend/training_instructor.py`: a brief built from the report (the
   operator's name replaced by "trainee", at most 40 SOE lines), a
   deterministic debrief in English or Spanish, and a Meta debrief
   through the existing `MetaProvider` with model `muse-spark-1.3`
   (override `META_MODEL`), 4000 output tokens (Muse Spark reasoning
   tokens count against the cap).
2. The system prompt forbids invented facts, references outside the
   drill, changing the score, and operating instructions for real
   equipment. A post-check lists standards the text names that the drill
   references do not contain ("unverified citations").
3. Cost: debrief after a finished drill only (no live hints), one call per
   report and language (SHA-256 cache, 64 entries), and a daily cap of
   its own, `META_INSTRUCTOR_DAILY_CAP`, default 20 calls per UTC day.
   No key, the cap reached, an error or an empty answer give the
   deterministic debrief, labelled with the reason.
4. Route `POST /api/training/debrief` (FACILITY_MANAGER), ledger action
   `TRAINING_DEBRIEF` with the report digest, source and model (not the
   text). Coach panel: EN / ES buttons, the source always shown.

## Consequences

- The Meta path was tested with a fake provider only: no key exists in
  this environment. The first real call happens on a host with
  `META_API_KEY`.
- The cap counts calls, not money; pricing and balance are read in the
  Meta console.
- Interlock refusal texts inside the debrief stay in English (they come
  from the plant), also in the Spanish deterministic debrief.
