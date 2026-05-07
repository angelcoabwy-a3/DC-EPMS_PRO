"""
DC-EPMS PRO - BMS Stub Connector
=================================
Simulates a Building Management System (BMS) connector exposing BACnet
and Modbus tags that a real Niagara N4 / Honeywell EBI / Schneider
EcoStruxure deployment would provide.

Architecture
------------
Real BMS deployments expose physical devices over OT networks via:
  - BACnet/IP (B/IP)        - HVAC, lighting, life safety
  - Modbus TCP / RTU        - power meters, UPS, generators
  - OPC-UA                  - higher-end PLCs and EnviroNet systems
  - SNMP                    - networking gear

This stub replaces the physical client with a tag catalog (loaded from
config/bms_tags.yml) where each tag is mapped to one of:
  - a static value (configuration)
  - a telemetry key (live from simulator)
  - a physics module metric (computed on demand)

This means the "BMS layer" responds to faults and load changes exactly
like a real BMS would, without requiring the physical hardware.

When deployed against a real BMS, the same tag catalog defines the
mapping between EPMS-internal names and the BMS namespace - changing
the source from `physics` to a real BACnet point ID.

Write capability
----------------
Writable tags accept commands (e.g., HVAC.CHWP1.SPEED setpoint changes).
Each write is logged with timestamp + originator for audit purposes
(NFPA 70B / NIST SP 800-82 OT operations).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("dc-epms.bms")


# ---------------------------------------------------------------------------
#  Data classes
# ---------------------------------------------------------------------------


@dataclass
class BMSTag:
    """Single BMS tag definition + cached current value."""

    id: str
    protocol: str  # "BACnet" | "Modbus" | "OPC-UA"
    object_type: str  # "AI"|"AO"|"BI"|"BO"|"MV"|"AV"|"HR"|"IR"
    units: str
    source: dict
    writable: bool = False
    description: str = ""
    location: str = ""
    alarm_band: list | None = None
    enum_values: list | None = None

    # Cached current value
    current_value: Any = None
    last_read_ts: float = 0.0
    last_write_ts: float = 0.0
    last_write_user: str = ""

    @property
    def category(self) -> str:
        """First segment of the tag id, e.g. HVAC / PWR / IT."""
        return self.id.split(".")[0] if "." in self.id else "MISC"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "object_type": self.object_type,
            "units": self.units,
            "writable": self.writable,
            "description": self.description,
            "location": self.location,
            "alarm_band": self.alarm_band,
            "enum_values": self.enum_values,
            "category": self.category,
            "current_value": self.current_value,
            "last_read_ts": self.last_read_ts,
            "last_write_ts": self.last_write_ts,
            "last_write_user": self.last_write_user,
            "alarm_state": self._alarm_state(),
        }

    def _alarm_state(self) -> str:
        """Compute alarm state based on band + current_value."""
        if self.alarm_band is None or self.current_value is None:
            return "normal"
        try:
            v = float(self.current_value)
            lo, hi = self.alarm_band
            if v < lo or v > hi:
                return "alarm"
            # Within 5% of the band edge -> warning
            band = hi - lo
            if (hi - v) < band * 0.05 or (v - lo) < band * 0.05:
                return "warning"
            return "normal"
        except (ValueError, TypeError):
            return "normal"


@dataclass
class WriteAuditEntry:
    """Audit log entry for a tag write."""

    ts: float
    tag_id: str
    old_value: Any
    new_value: Any
    user: str
    success: bool = True
    error: str = ""


# ---------------------------------------------------------------------------
#  BMSConnector
# ---------------------------------------------------------------------------


class BMSConnector:
    """Stub BMS connector that resolves tags from telemetry + physics.

    In a real deployment, the resolver would maintain BACnet/Modbus
    client connections to physical controllers. This stub uses the
    same tag catalog format but evaluates sources against the in-memory
    physics engine and live telemetry.
    """

    def __init__(self, tag_catalog_path: Path, project_root: Path):
        self.catalog_path = tag_catalog_path
        self.project_root = project_root
        self.tags: dict[str, BMSTag] = {}
        self.categories: dict[str, dict] = {}
        self.write_audit_log: list[WriteAuditEntry] = []
        self._load_catalog()

    def _load_catalog(self) -> None:
        if not self.catalog_path.exists():
            log.error("BMS catalog not found: %s", self.catalog_path)
            return
        try:
            data = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("Failed to load BMS catalog: %s", e)
            return
        for t in data.get("tags", []):
            try:
                tag = BMSTag(
                    id=t["id"],
                    protocol=t["protocol"],
                    object_type=t["object_type"],
                    units=t["units"],
                    source=t.get("source", {}),
                    writable=bool(t.get("writable", False)),
                    description=t.get("description", ""),
                    location=t.get("location", ""),
                    alarm_band=t.get("alarm_band"),
                    enum_values=t.get("enum_values"),
                )
                self.tags[tag.id] = tag
            except Exception as e:
                log.warning("Skipping invalid tag %s: %s", t.get("id"), e)
        self.categories = data.get("categories", {})
        log.info(
            "BMS connector loaded %d tags across %d categories",
            len(self.tags),
            len(self.categories),
        )

    # ------------------------------------------------------------------ #
    #  Tag value resolution
    # ------------------------------------------------------------------ #

    def _resolve_source(
        self,
        source: dict,
        telemetry: dict,
        physics_metrics: dict,
    ) -> Any:
        """Resolve a tag value from its source descriptor."""
        src_type = source.get("type", "static")

        if src_type == "static":
            return source.get("value")

        if src_type == "telemetry":
            key = source.get("key")
            if not key or key not in telemetry:
                return None
            value = telemetry[key]
            transform = source.get("transform")
            if transform:
                value = self._apply_transform(value, transform)
            return value

        if src_type == "physics":
            module = source.get("module")
            metric = source.get("metric")
            if not module or not metric:
                return None
            mod_metrics = physics_metrics.get(module, {})
            value = mod_metrics.get(metric)
            if value is None:
                return None
            transform = source.get("transform")
            if transform:
                value = self._apply_transform(value, transform)
            return value

        return None

    @staticmethod
    def _apply_transform(value: float, expr: str) -> float:
        """Apply a small expression like 'x/60*100' to a numeric value.

        Only allows arithmetic on x; no function calls. Returns original
        value on parse failure.
        """
        try:
            x = float(value)
            # Allow only digits, x, ops, parens, dot, space
            allowed = set("0123456789x+-*/(). ")
            if not all(c in allowed for c in expr):
                return value
            # eval with minimal namespace
            return eval(expr, {"__builtins__": None}, {"x": x})
        except Exception:
            return value

    def refresh(
        self,
        telemetry: dict,
        physics_metrics: dict,
    ) -> None:
        """Update current_value on all tags using fresh data."""
        ts = time.time()
        for tag in self.tags.values():
            try:
                value = self._resolve_source(tag.source, telemetry, physics_metrics)
                # Round numerics for display sanity
                if isinstance(value, float):
                    if math.isfinite(value):
                        value = round(value, 3)
                    else:
                        value = None
                tag.current_value = value
                tag.last_read_ts = ts
            except Exception as e:
                log.debug("refresh tag %s failed: %s", tag.id, e)

    # ------------------------------------------------------------------ #
    #  Public read/write API
    # ------------------------------------------------------------------ #

    def read(self, tag_id: str) -> BMSTag | None:
        return self.tags.get(tag_id)

    def list_tags(
        self,
        category: str | None = None,
    ) -> list[BMSTag]:
        if category is None:
            return sorted(self.tags.values(), key=lambda t: t.id)
        return sorted(
            (t for t in self.tags.values() if t.category == category),
            key=lambda t: t.id,
        )

    def write(
        self,
        tag_id: str,
        value: Any,
        user: str = "operator",
    ) -> tuple[bool, str]:
        """Issue a write command against a writable tag.

        Returns (success, message). Logged to write_audit_log.
        """
        tag = self.tags.get(tag_id)
        if not tag:
            entry = WriteAuditEntry(
                ts=time.time(),
                tag_id=tag_id,
                old_value=None,
                new_value=value,
                user=user,
                success=False,
                error="Tag not found",
            )
            self.write_audit_log.append(entry)
            return False, f"Tag '{tag_id}' not found"

        if not tag.writable:
            entry = WriteAuditEntry(
                ts=time.time(),
                tag_id=tag_id,
                old_value=tag.current_value,
                new_value=value,
                user=user,
                success=False,
                error="Tag is read-only",
            )
            self.write_audit_log.append(entry)
            return False, f"Tag '{tag_id}' is read-only"

        # For enum tags, validate value
        if tag.enum_values and str(value) not in tag.enum_values:
            entry = WriteAuditEntry(
                ts=time.time(),
                tag_id=tag_id,
                old_value=tag.current_value,
                new_value=value,
                user=user,
                success=False,
                error=f"Value must be one of {tag.enum_values}",
            )
            self.write_audit_log.append(entry)
            return False, f"Invalid enum value. Must be one of: {', '.join(tag.enum_values)}"

        # For analog tags with alarm_band, warn on out-of-range
        warning = ""
        if tag.alarm_band:
            try:
                v = float(value)
                lo, hi = tag.alarm_band
                if v < lo or v > hi:
                    warning = f" (warning: value outside band [{lo}, {hi}])"
            except (ValueError, TypeError):
                pass

        old_value = tag.current_value
        tag.current_value = value
        tag.last_write_ts = time.time()
        tag.last_write_user = user

        entry = WriteAuditEntry(
            ts=time.time(),
            tag_id=tag_id,
            old_value=old_value,
            new_value=value,
            user=user,
            success=True,
        )
        self.write_audit_log.append(entry)

        # Truncate audit log to last 200 entries
        if len(self.write_audit_log) > 200:
            self.write_audit_log = self.write_audit_log[-200:]

        return True, f"Wrote {value} to {tag_id}{warning}"

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Return recent write audit entries (newest first)."""
        return [
            {
                "ts": e.ts,
                "tag_id": e.tag_id,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "user": e.user,
                "success": e.success,
                "error": e.error,
            }
            for e in reversed(self.write_audit_log[-limit:])
        ]

    def stats(self) -> dict:
        """Return summary statistics for the BMS connector."""
        by_protocol = {}
        by_category = {}
        alarm_count = 0
        warning_count = 0
        for tag in self.tags.values():
            by_protocol[tag.protocol] = by_protocol.get(tag.protocol, 0) + 1
            by_category[tag.category] = by_category.get(tag.category, 0) + 1
            state = tag._alarm_state()
            if state == "alarm":
                alarm_count += 1
            elif state == "warning":
                warning_count += 1
        return {
            "total_tags": len(self.tags),
            "writable_tags": sum(1 for t in self.tags.values() if t.writable),
            "by_protocol": by_protocol,
            "by_category": by_category,
            "alarm_count": alarm_count,
            "warning_count": warning_count,
            "audit_entries": len(self.write_audit_log),
            "categories": self.categories,
        }


# ---------------------------------------------------------------------------
#  Singleton
# ---------------------------------------------------------------------------

_instance: BMSConnector | None = None


def get_bms(project_root: Path) -> BMSConnector:
    """Get the shared BMSConnector instance."""
    global _instance
    if _instance is None:
        catalog_path = project_root / "config" / "bms_tags.yml"
        _instance = BMSConnector(catalog_path, project_root)
    return _instance
