"""
backend/ups_bypass.py
=====================
L4 (2026-11-26) -- System-level breakers of the UPS bank of one path and
its external maintenance bypass, as an operator handles them:

  Q1   rectifier (unit) input breaker          (UIB)
  Q2   static-bypass input breaker             (SSIB / BIB)
  Q4   maintenance isolation breaker, output   (MIB / UOB)
  Q3   maintenance bypass breaker, wrap-around (MBB)
  QF1  battery breaker, shunt trip, padlock hasp

and the two-lock key interlock with a solenoid key release unit (SKRU):
two keys keyed alike. In normal service one key is trapped in the MIB
lock (MIB free to close) and the other is captured in the SKRU; the MBB
is locked open. The SKRU releases its key only with the UPS on static
bypass and the bypass source live (output in phase with the bypass).
Forward: release key -> unlock MBB -> close MBB -> open MIB -> lock MIB
-> return that key to the SKRU. Return: mirror image. So MBB can never be
closed onto an inverter, and MIB is never opened before MBB is closed.

Sequence grounded on vendor manuals (checked 2026-11-26): Toshiba G9000
MBS operation (UPS to static bypass, key from the SKRU, unlock and close
MBB, open MIB, lock MIB and return its key, DC breakers off, UIB off);
Schneider Galaxy VX shut-down to maintenance bypass (same order with
UOB / SSIB); Powerware 9315 MBM (the SKRU withholds the key needed to
start the transfer). The two-keys-keyed-alike chain is this model's
reading of those procedures; a real site follows its own key drawing.

PURE: no clock, no I/O. Block states (inverter / static bypass) belong
to the device controller; this module receives them in the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BREAKERS = ("Q1", "Q2", "Q3", "Q4", "QF1")
BREAKER_NAMES = {
    "Q1": "Rectifier input (UIB)", "Q2": "Static-bypass input (SSIB)",
    "Q3": "Maintenance bypass (MBB)", "Q4": "Maintenance isolation (MIB)",
    "QF1": "Battery breaker",
}

ACTIONS = (
    "SYSTEM_TO_BYPASS", "SYSTEM_TO_INVERTER",
    "CLOSE_Q1", "OPEN_Q1", "CLOSE_Q2", "OPEN_Q2", "CLOSE_Q3", "OPEN_Q3",
    "CLOSE_Q4", "OPEN_Q4", "CLOSE_QF1", "OPEN_QF1",
    "SKRU_RELEASE", "SKRU_CAPTURE", "UNLOCK_MBB", "LOCK_MBB", "UNLOCK_MIB", "LOCK_MIB",
    "PADLOCK_QF1", "UNPADLOCK_QF1",
)
ACTION_LABELS = {
    "SYSTEM_TO_BYPASS": "UPS display: transfer the load to static bypass",
    "SYSTEM_TO_INVERTER": "UPS display: transfer the load to the inverter",
    "CLOSE_Q1": "Close Q1 rectifier input", "OPEN_Q1": "Open Q1 rectifier input",
    "CLOSE_Q2": "Close Q2 static-bypass input", "OPEN_Q2": "Open Q2 static-bypass input",
    "CLOSE_Q3": "Close Q3 maintenance bypass (MBB)", "OPEN_Q3": "Open Q3 maintenance bypass (MBB)",
    "CLOSE_Q4": "Close Q4 maintenance isolation (MIB)", "OPEN_Q4": "Open Q4 maintenance isolation (MIB)",
    "CLOSE_QF1": "Close QF1 battery breaker", "OPEN_QF1": "Open QF1 battery breaker",
    "SKRU_RELEASE": "Take the key from the solenoid key release unit",
    "SKRU_CAPTURE": "Return a key to the solenoid key release unit",
    "UNLOCK_MBB": "Unlock MBB with a key", "LOCK_MBB": "Lock MBB open and take the key",
    "UNLOCK_MIB": "Unlock MIB with a key", "LOCK_MIB": "Lock MIB open and take the key",
    "PADLOCK_QF1": "Apply personal padlock to QF1", "UNPADLOCK_QF1": "Remove personal padlock from QF1",
}

INVERTER, STATIC_BYPASS, MIXED, OFF = "INVERTER", "STATIC_BYPASS", "MIXED", "OFF"


@dataclass
class UpsSystem:
    path: str
    q1: bool = True
    q2: bool = True
    q3: bool = False
    q4: bool = True
    qf1: bool = True
    qf1_padlock: str | None = None
    mib_key: bool = True        # key trapped in the MIB lock: MIB unlocked
    mbb_key: bool = False       # key trapped in the MBB lock: MBB unlocked
    skru_keys: int = 1
    hand_keys: int = 0
    parked: list[str] = field(default_factory=list)   # blocks de-energized by Q1/Q2/Q4


@dataclass(frozen=True)
class UpsContext:
    mode: str                  # INVERTER / STATIC_BYPASS / MIXED / OFF (carrying blocks)
    bus_live: bool             # 480 V / MV source upstream of Q1 and Q2
    blocks_faulted: int = 0
    actor: str = ""


def bypass_live(s: UpsSystem, ctx: UpsContext) -> bool:
    return ctx.bus_live and s.q2


def rect_live(s: UpsSystem, ctx: UpsContext) -> bool:
    return ctx.bus_live and s.q1


def skru_permits(s: UpsSystem, ctx: UpsContext) -> bool:
    """'OK to transfer' lamp: UPS output on static bypass, bypass live."""
    return ctx.mode == STATIC_BYPASS and bypass_live(s, ctx)


def load_source(s: UpsSystem, ctx: UpsContext) -> str:
    if s.q3 and ctx.bus_live:
        return "MAINTENANCE_BYPASS"
    if s.q4 and ctx.mode in (INVERTER, STATIC_BYPASS, MIXED):
        return ctx.mode
    return "NONE"


def interlock(s: UpsSystem, action: str, ctx: UpsContext) -> str | None:
    if action not in ACTIONS:
        return f"unknown UPS system action {action!r}"
    if action == "SYSTEM_TO_BYPASS":
        if ctx.mode == STATIC_BYPASS:
            return "The UPS is already on static bypass."
        if ctx.mode == OFF:
            return "No UPS block is carrying: nothing to transfer."
        if not bypass_live(s, ctx):
            return "Bypass source not available (Q2 open or no voltage): transfer refused."
        return None
    if action == "SYSTEM_TO_INVERTER":
        if s.q3:
            return "MBB (Q3) is closed: the inverter must not parallel the maintenance bypass."
        if s.skru_keys == 0:
            return "A key is out of the SKRU: the UPS is held on static bypass."
        if not rect_live(s, ctx):
            return "Rectifier input not available (Q1 open or no voltage)."
        if ctx.mode not in (STATIC_BYPASS, MIXED):
            return "No block is on static bypass."
        return None
    if action.startswith(("CLOSE_", "OPEN_")):
        closing = action.startswith("CLOSE_")
        brk = action.split("_", 1)[1]
        cur = getattr(s, brk.lower())
        if cur == closing:
            return f"{brk} is already {'closed' if closing else 'open'}."
        if brk == "Q3" and closing and not s.mbb_key:
            return "MBB is locked open: unlock it with the key from the SKRU."
        if brk == "Q4" and closing and not s.mib_key:
            return "MIB is locked open: unlock it with the key from the SKRU."
        if brk == "Q4" and not closing and not s.q3:
            return ("Opening MIB with MBB open would drop the critical load: close MBB first "
                    "(make before break).")
        if brk == "Q3" and not closing and not (s.q4 and ctx.mode in (STATIC_BYPASS, MIXED, INVERTER)):
            return ("Opening MBB now would drop the critical load: the UPS output (MIB closed, "
                    "UPS on static bypass) must carry it first.")
        if brk == "QF1" and closing and s.qf1_padlock:
            return f"QF1 is padlocked by {s.qf1_padlock}."
        return None
    if action == "SKRU_RELEASE":
        if s.skru_keys == 0:
            return "The SKRU holds no key."
        if not skru_permits(s, ctx):
            return "SKRU lamp off: the key is released only with the UPS on static bypass and the bypass live."
        return None
    if action == "SKRU_CAPTURE":
        if s.hand_keys == 0:
            return "You hold no key."
        if s.skru_keys >= 1:
            return "The SKRU already holds a key."
        return None
    if action in ("UNLOCK_MBB", "UNLOCK_MIB"):
        trapped = s.mbb_key if action == "UNLOCK_MBB" else s.mib_key
        if trapped:
            return "That lock is already unlocked."
        return None if s.hand_keys else "You hold no key."
    if action in ("LOCK_MBB", "LOCK_MIB"):
        mbb = action == "LOCK_MBB"
        if not (s.mbb_key if mbb else s.mib_key):
            return "That breaker is already locked open."
        if (s.q3 if mbb else s.q4):
            return f"{'MBB' if mbb else 'MIB'} is closed: the lock bolt cannot be thrown."
        return None
    if action == "PADLOCK_QF1":
        if s.qf1_padlock:
            return f"QF1 is already padlocked by {s.qf1_padlock}."
        return "Open QF1 before applying the padlock." if s.qf1 else None
    if action == "UNPADLOCK_QF1":
        if not s.qf1_padlock:
            return "No padlock on QF1."
        if ctx.actor and s.qf1_padlock != ctx.actor:
            return f"Only {s.qf1_padlock}, who applied the padlock, may remove it."
        return None
    return None


def apply(s: UpsSystem, action: str, ctx: UpsContext) -> str | None:
    """Apply a permitted action. Returns a block effect for the
    controller: "to_bypass", "to_inverter", "park", "unpark" or None."""
    if action == "SYSTEM_TO_BYPASS":
        return "to_bypass"
    if action == "SYSTEM_TO_INVERTER":
        return "to_inverter"
    if action.startswith(("CLOSE_", "OPEN_")):
        brk = action.split("_", 1)[1].lower()
        setattr(s, brk, action.startswith("CLOSE_"))
        if not s.q1 and not s.q2 and not s.q4:
            return "park"
        if brk == "q2" and s.q2 and s.parked:
            return "unpark"
        return None
    if action == "SKRU_RELEASE":
        s.skru_keys, s.hand_keys = 0, s.hand_keys + 1
    elif action == "SKRU_CAPTURE":
        s.skru_keys, s.hand_keys = 1, s.hand_keys - 1
    elif action == "UNLOCK_MBB":
        s.mbb_key, s.hand_keys = True, s.hand_keys - 1
    elif action == "UNLOCK_MIB":
        s.mib_key, s.hand_keys = True, s.hand_keys - 1
    elif action == "LOCK_MBB":
        s.mbb_key, s.hand_keys = False, s.hand_keys + 1
    elif action == "LOCK_MIB":
        s.mib_key, s.hand_keys = False, s.hand_keys + 1
    elif action == "PADLOCK_QF1":
        s.qf1_padlock = ctx.actor or "operator"
    elif action == "UNPADLOCK_QF1":
        s.qf1_padlock = None
    return None


def describe(s: UpsSystem, ctx: UpsContext) -> dict[str, Any]:
    return {
        "breakers": {b: getattr(s, b.lower()) for b in BREAKERS},
        "names": BREAKER_NAMES,
        "qf1_padlock": s.qf1_padlock,
        "mib_unlocked": s.mib_key, "mbb_unlocked": s.mbb_key,
        "skru_keys": s.skru_keys, "hand_keys": s.hand_keys,
        "skru_lamp": skru_permits(s, ctx),
        "mode": ctx.mode, "load_source": load_source(s, ctx),
        "bypass_live": bypass_live(s, ctx), "rect_live": rect_live(s, ctx),
        "parked": list(s.parked),
        "on_maintenance_bypass": s.q3,
        "actions": [
            {"action": a, "label": ACTION_LABELS[a],
             "permitted": (r := interlock(s, a, ctx)) is None, "blocked_reason": r}
            for a in ACTIONS
        ],
    }
