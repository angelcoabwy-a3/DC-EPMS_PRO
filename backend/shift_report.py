"""
DC-EPMS PRO — Shift Report PDF Generator
==========================================
Generates professional shift turnover reports from PostgreSQL data.
Output: downloadable PDF ready for supervisor sign-off.

Format follows Schneider Electric SE Blog shift-report standard:
  - Shift metadata (operator, times, facility)
  - Telemetry summary (PUE/temp trends, anomalies)
  - Incidents log (open/closed with timestamps)
  - Procedures completed (MOPs/EOPs)
  - Open items for next shift
  - Operator signature block
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

log = logging.getLogger("dc-epms.shift_report")


class ShiftReportGenerator:
    """Builds Tier IV 2N compliant shift turnover PDFs for a3semi."""

    BRAND_CYAN  = colors.HexColor("#00B8D4")  # A-Cubed cyan
    BRAND_DARK  = colors.HexColor("#1E1E1E")
    OK_GREEN    = colors.HexColor("#107C10")
    WARN_AMBER  = colors.HexColor("#F2A900")
    CRIT_RED    = colors.HexColor("#D13438")
    SOFT_GRAY   = colors.HexColor("#F3F2F1")
    BORDER_GRAY = colors.HexColor("#D1D1D1")

    def __init__(self, facility_name: str = "A3-Alpha Toronto Area",
                 facility_tier: str = "Tier IV 2N 40MW · a3semi"):
        self.facility_name = facility_name
        self.facility_tier = facility_tier
        self._styles = self._build_styles()

    def _build_styles(self):
        s = getSampleStyleSheet()
        s.add(ParagraphStyle(
            "ReportTitle", parent=s["Heading1"],
            fontSize=18, textColor=self.BRAND_CYAN,
            spaceAfter=4, alignment=0,
        ))
        s.add(ParagraphStyle(
            "ReportSubtitle", parent=s["Normal"],
            fontSize=10, textColor=colors.grey,
            spaceAfter=14,
        ))
        s.add(ParagraphStyle(
            "SectionHdr", parent=s["Heading2"],
            fontSize=12, textColor=self.BRAND_DARK,
            spaceBefore=12, spaceAfter=6,
            borderPadding=0,
        ))
        s.add(ParagraphStyle(
            "Body", parent=s["Normal"],
            fontSize=9, leading=12, textColor=self.BRAND_DARK,
        ))
        s.add(ParagraphStyle(
            "Small", parent=s["Normal"],
            fontSize=8, textColor=colors.grey,
        ))
        s.add(ParagraphStyle(
            "Sig", parent=s["Normal"],
            fontSize=9, leading=14, spaceBefore=24,
        ))
        return s

    def generate(
        self,
        operator: str,
        shift_id: str,
        shift_start: datetime,
        shift_end: datetime,
        telemetry_rows: list[dict],
        incidents: list[dict],
        procedures_completed: list[dict] = None,
        open_items: list[str] = None,
    ) -> bytes:
        """Render PDF and return as bytes."""
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            rightMargin=0.6 * inch, leftMargin=0.6 * inch,
            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
            title=f"Shift Report {shift_id}",
            author=operator,
        )
        story = []

        # ── Header ────────────────────────────────────────────
        story.append(Paragraph(
            f"Shift Turnover Report · {shift_id}",
            self._styles["ReportTitle"]
        ))
        story.append(Paragraph(
            f"{self.facility_name} · {self.facility_tier}",
            self._styles["ReportSubtitle"]
        ))

        # ── Metadata table ────────────────────────────────────
        dur_h = (shift_end - shift_start).total_seconds() / 3600
        meta = [
            ["Operator",        operator],
            ["Shift ID",        shift_id],
            ["Shift start",     shift_start.strftime("%Y-%m-%d %H:%M %Z")],
            ["Shift end",       shift_end.strftime("%Y-%m-%d %H:%M %Z")],
            ["Duration",        f"{dur_h:.1f} hours"],
            ["Report generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
        ]
        tbl = Table(meta, colWidths=[1.6 * inch, 4.6 * inch])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), self.SOFT_GRAY),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, self.BORDER_GRAY),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ]))
        story.append(tbl)

        # ── Telemetry summary ─────────────────────────────────
        story.append(Paragraph("Telemetry Summary", self._styles["SectionHdr"]))
        story.extend(self._telemetry_section(telemetry_rows))

        # ── Incidents ─────────────────────────────────────────
        story.append(Paragraph("Incidents", self._styles["SectionHdr"]))
        story.extend(self._incidents_section(incidents))

        # ── Procedures completed ──────────────────────────────
        if procedures_completed:
            story.append(Paragraph("Procedures Completed", self._styles["SectionHdr"]))
            story.extend(self._procedures_section(procedures_completed))

        # ── Open items for next shift ─────────────────────────
        story.append(Paragraph("Open Items for Next Shift", self._styles["SectionHdr"]))
        if open_items:
            for item in open_items:
                story.append(Paragraph(f"• {item}", self._styles["Body"]))
        else:
            story.append(Paragraph("No open items — clean handover.",
                                   self._styles["Body"]))

        # ── Signature block ───────────────────────────────────
        story.append(Spacer(1, 30))
        sig_data = [
            ["Outgoing Operator",  "Incoming Operator"],
            ["", ""],  # signature space
            [f"{operator}", "_" * 30],
            [shift_end.strftime("%Y-%m-%d %H:%M"), "Date / Time"],
        ]
        sig_tbl = Table(sig_data, colWidths=[3.1 * inch, 3.1 * inch])
        sig_tbl.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEABOVE", (0, 2), (-1, 2), 0.5, self.BRAND_DARK),
            ("TOPPADDING", (0, 1), (-1, 1), 30),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
        ]))
        story.append(sig_tbl)

        # ── Footer ────────────────────────────────────────────
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            f"Generated by DC-EPMS PRO (a3semi proprietary) | · Compliance: CSA Z462 · NFPA 70E · "
            f"NFPA 110 · ASHRAE A2 · IEC 62443 · ISO 22301",
            self._styles["Small"],
        ))

        doc.build(story, onFirstPage=self._header_footer,
                  onLaterPages=self._header_footer)
        return buf.getvalue()

    def _telemetry_section(self, rows: list[dict]) -> list:
        out = []
        if not rows:
            out.append(Paragraph(
                "No telemetry points recorded during shift.",
                self._styles["Body"]
            ))
            return out

        # Calculate summary statistics
        pues = [r["pue"] for r in rows if "pue" in r]
        temps = [r["hall_temp_c"] for r in rows if "hall_temp_c" in r]
        loads = [r["it_load_kw"] for r in rows if "it_load_kw" in r]

        stats = [
            ["Metric", "Min", "Avg", "Max", "Status"],
            [
                "PUE",
                f"{min(pues):.3f}" if pues else "—",
                f"{sum(pues)/len(pues):.3f}" if pues else "—",
                f"{max(pues):.3f}" if pues else "—",
                self._pue_status(max(pues) if pues else 0),
            ],
            [
                "Hall Temperature (°C)",
                f"{min(temps):.1f}" if temps else "—",
                f"{sum(temps)/len(temps):.1f}" if temps else "—",
                f"{max(temps):.1f}" if temps else "—",
                self._temp_status(max(temps) if temps else 0),
            ],
            [
                "IT Load (kW)",
                f"{min(loads):,.0f}" if loads else "—",
                f"{sum(loads)/len(loads):,.0f}" if loads else "—",
                f"{max(loads):,.0f}" if loads else "—",
                "Nominal",
            ],
        ]
        tbl = Table(stats, colWidths=[
            1.9 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 1.6 * inch
        ])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), self.BRAND_CYAN),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID", (0, 0), (-1, -1), 0.25, self.BORDER_GRAY),
            ("ALIGN", (1, 1), (3, -1), "RIGHT"),
            ("ALIGN", (4, 1), (4, -1), "CENTER"),
        ]))
        out.append(tbl)
        out.append(Paragraph(
            f"Telemetry samples: {len(rows)} points",
            self._styles["Small"]
        ))
        return out

    def _incidents_section(self, incidents: list[dict]) -> list:
        out = []
        if not incidents:
            out.append(Paragraph(
                "No incidents recorded during shift.",
                self._styles["Body"]
            ))
            return out

        data = [["ID", "Time", "Severity", "Source", "Title", "Status"]]
        for inc in incidents[:15]:  # cap at 15 rows per page
            ts_str = inc.get("ts", "")
            if isinstance(ts_str, str) and len(ts_str) >= 16:
                ts_str = ts_str[11:16]  # HH:MM
            data.append([
                inc.get("incident_id", "—")[-10:],
                ts_str,
                inc.get("severity", "info").upper()[:4],
                inc.get("source", "—")[:12],
                inc.get("title", "—")[:34],
                inc.get("status", "OPEN")[:6],
            ])
        tbl = Table(data, colWidths=[
            0.9 * inch, 0.5 * inch, 0.55 * inch,
            0.9 * inch, 2.4 * inch, 0.6 * inch,
        ])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), self.BRAND_DARK),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("LEFTPADDING",  (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.25, self.BORDER_GRAY),
        ]))
        # Color-code severity column
        for i, inc in enumerate(incidents[:15], start=1):
            sev = inc.get("severity", "info").lower()
            if sev in ("critical", "crit"):
                tbl.setStyle(TableStyle([
                    ("TEXTCOLOR", (2, i), (2, i), self.CRIT_RED),
                    ("FONTNAME",  (2, i), (2, i), "Helvetica-Bold"),
                ]))
            elif sev in ("warning", "warn"):
                tbl.setStyle(TableStyle([
                    ("TEXTCOLOR", (2, i), (2, i), self.WARN_AMBER),
                ]))
        out.append(tbl)
        if len(incidents) > 15:
            out.append(Paragraph(
                f"... plus {len(incidents) - 15} additional incidents (see full log)",
                self._styles["Small"]
            ))
        return out

    def _procedures_section(self, procedures: list[dict]) -> list:
        out = []
        for proc in procedures[:10]:
            out.append(Paragraph(
                f"<b>{proc.get('id', '—')}</b> — {proc.get('title', '—')} "
                f"({proc.get('type', 'Procedure')})",
                self._styles["Body"]
            ))
        return out

    def _pue_status(self, pue: float) -> str:
        if pue <= 1.20:
            return "Excellent"
        if pue <= 1.30:
            return "Target"
        if pue <= 1.40:
            return "Acceptable"
        return "Above threshold"

    def _temp_status(self, t: float) -> str:
        if t < 27:
            return "ASHRAE A2 OK"
        if t < 32:
            return "Warm"
        if t < 35:
            return "Approach limit"
        return "CRITICAL"

    def _header_footer(self, canvas, doc):
        """Page header with facility branding + footer with page number."""
        canvas.saveState()
        # Thin top accent line
        canvas.setStrokeColor(self.BRAND_CYAN)
        canvas.setLineWidth(2)
        canvas.line(0.6 * inch, 10.7 * inch, 8.0 * inch, 10.7 * inch)

        # Page footer
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            0.6 * inch, 0.3 * inch,
            f"DC-EPMS PRO · {self.facility_name} · Confidential"
        )
        canvas.drawRightString(
            8.0 * inch, 0.3 * inch,
            f"Page {doc.page}"
        )
        canvas.restoreState()
