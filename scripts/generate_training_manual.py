"""
Generate the a3semi CET Training Manual PDF from the corpus.

This is the centerpiece portfolio document - a ~40-60 page professional
training manual compiled from the Tier 1-4 corpus.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_ROOT = ROOT / "data" / "corpus"
OUTPUT_PDF = ROOT / "a3semi_CET_Training_Manual.pdf"

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# a3semi color palette
A3_CYAN = colors.HexColor("#00B8D4")
A3_ANTHRACITE = colors.HexColor("#0B0D10")
A3_GRAPHITE = colors.HexColor("#14181D")
A3_SLATE = colors.HexColor("#1C2128")
A3_TEXT = colors.HexColor("#E8EAED")
A3_MUTED = colors.HexColor("#9AA0A6")
A3_CRIT = colors.HexColor("#E53935")
A3_WARN = colors.HexColor("#FB8C00")

TIER_COLORS = {
    1: A3_CRIT,
    2: A3_WARN,
    3: A3_CYAN,
    4: colors.HexColor("#4CAF50"),
}

TIER_NAMES = {
    1: "Safety Procedures",
    2: "Vendor Procedures",
    3: "Standards &amp; Physics",
    4: "a3semi MOPs &amp; EOPs",
}

TIER_DESCRIPTIONS = {
    1: (
        "Life-safety procedures that take absolute priority over all "
        "operational concerns. LOTO, arc flash, confined space, fire, "
        "and EPO are non-negotiable. These procedures are the foundation "
        "of every activity at A3-Alpha Toronto Area."
    ),
    2: (
        "Equipment-specific vendor procedures derived from manufacturer "
        "engineering guides. Apply to the specific hardware deployed at "
        "A3-Alpha. These procedures satisfy warranty requirements and "
        "provide manufacturer-validated operating envelopes."
    ),
    3: (
        "Industry standards and thermal physics that govern facility "
        "operations. These establish the boundaries within which all "
        "operational decisions are made."
    ),
    4: (
        "Site-specific procedures written by a3semi facility engineering "
        "for the A3-Alpha Toronto Area facility. Day-to-day operational "
        "procedures executed by the NOC and maintenance teams."
    ),
}


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    meta_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1 :]).strip()
    metadata = {}
    for line in meta_lines:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        if value.startswith("[") and value.endswith("]"):
            value = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        elif value.isdigit():
            value = int(value)
        else:
            value = value.strip("'\"")
        metadata[key] = value
    return metadata, body


def escape_html(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_md(text):
    text = escape_html(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier" color="#00B8D4">\1</font>', text)
    return text


def md_to_flowables(text, styles):
    flowables = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line:
            flowables.append(Spacer(1, 0.08 * inch))
            i += 1
            continue

        if line.startswith("# "):
            flowables.append(Paragraph(escape_html(line[2:]), styles["h1"]))
            flowables.append(Spacer(1, 0.1 * inch))
        elif line.startswith("## "):
            flowables.append(Paragraph(escape_html(line[3:]), styles["h2"]))
            flowables.append(Spacer(1, 0.08 * inch))
        elif line.startswith("### "):
            flowables.append(Paragraph(escape_html(line[4:]), styles["h3"]))
            flowables.append(Spacer(1, 0.06 * inch))
        elif line.startswith("#### "):
            flowables.append(Paragraph(escape_html(line[5:]), styles["h4"]))

        elif line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            code_text = "<br/>".join(escape_html(c) for c in code_lines)
            flowables.append(Paragraph(code_text, styles["code"]))
            flowables.append(Spacer(1, 0.08 * inch))

        elif line.startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|"):
            table_lines = [line]
            j = i + 1
            while j < len(lines) and lines[j].startswith("|"):
                table_lines.append(lines[j])
                j += 1
            tbl_data = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):
                    continue
                tbl_data.append([Paragraph(inline_md(c), styles["tblcell"]) for c in cells])
            if tbl_data:
                tbl = Table(tbl_data, hAlign="LEFT")
                tbl.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), A3_SLATE),
                            ("TEXTCOLOR", (0, 0), (-1, 0), A3_CYAN),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("GRID", (0, 0), (-1, -1), 0.5, A3_MUTED),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                flowables.append(tbl)
                flowables.append(Spacer(1, 0.1 * inch))
            i = j - 1

        elif line.startswith("- ") or line.startswith("* "):
            flowables.append(
                Paragraph("&bull;&nbsp;&nbsp;" + inline_md(line[2:]), styles["bullet"])
            )

        elif re.match(r"^\d+\.\s", line):
            flowables.append(Paragraph(inline_md(line), styles["bullet"]))

        else:
            flowables.append(Paragraph(inline_md(line), styles["body"]))

        i += 1

    return flowables


def build_styles():
    return {
        "title": ParagraphStyle(
            "title",
            fontSize=28,
            textColor=A3_TEXT,
            alignment=TA_CENTER,
            spaceAfter=20,
            fontName="Helvetica-Bold",
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontSize=14,
            textColor=A3_CYAN,
            alignment=TA_CENTER,
            spaceAfter=8,
            fontName="Helvetica",
        ),
        "h1": ParagraphStyle(
            "h1",
            fontSize=22,
            textColor=A3_CYAN,
            spaceBefore=12,
            spaceAfter=10,
            fontName="Helvetica-Bold",
        ),
        "h2": ParagraphStyle(
            "h2",
            fontSize=15,
            textColor=A3_TEXT,
            spaceBefore=10,
            spaceAfter=6,
            fontName="Helvetica-Bold",
        ),
        "h3": ParagraphStyle(
            "h3",
            fontSize=12,
            textColor=A3_CYAN,
            spaceBefore=8,
            spaceAfter=4,
            fontName="Helvetica-Bold",
        ),
        "h4": ParagraphStyle(
            "h4",
            fontSize=10,
            textColor=A3_TEXT,
            spaceBefore=6,
            spaceAfter=3,
            fontName="Helvetica-Bold",
        ),
        "body": ParagraphStyle(
            "body",
            fontSize=10,
            textColor=A3_TEXT,
            spaceAfter=4,
            leading=14,
            fontName="Helvetica",
            alignment=TA_JUSTIFY,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontSize=10,
            textColor=A3_TEXT,
            leftIndent=14,
            spaceAfter=2,
            leading=13,
            fontName="Helvetica",
        ),
        "code": ParagraphStyle(
            "code",
            fontSize=8,
            textColor=A3_TEXT,
            backColor=A3_SLATE,
            fontName="Courier",
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=4,
            leading=11,
        ),
        "tblcell": ParagraphStyle(
            "tblcell",
            fontSize=8,
            textColor=A3_TEXT,
            fontName="Helvetica",
            leading=10,
        ),
        "meta": ParagraphStyle(
            "meta",
            fontSize=9,
            textColor=A3_MUTED,
            fontName="Helvetica-Oblique",
            spaceAfter=8,
        ),
        "tier_desc": ParagraphStyle(
            "tier_desc",
            fontSize=11,
            textColor=A3_TEXT,
            alignment=TA_JUSTIFY,
            fontName="Helvetica",
            leading=16,
            spaceAfter=20,
        ),
    }


def draw_page_background(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(A3_ANTHRACITE)
    canvas.rect(0, 0, letter[0], letter[1], fill=1, stroke=0)
    canvas.setFillColor(A3_CYAN)
    canvas.rect(0, letter[1] - 8, letter[0], 8, fill=1, stroke=0)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(A3_MUTED)
    canvas.drawString(
        0.75 * inch,
        0.5 * inch,
        "A-Cubed Semiconductor Systems Inc.  |  A3-Alpha Toronto Area  |  "
        "CONFIDENTIAL - Internal Training Material",
    )
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def build_cover(styles):
    flowables = [Spacer(1, 1.8 * inch)]
    logo_style = ParagraphStyle(
        "logo",
        fontSize=48,
        textColor=A3_CYAN,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        spaceAfter=8,
    )
    flowables.append(Paragraph("a3semi", logo_style))

    tagline_style = ParagraphStyle(
        "tagline",
        fontSize=11,
        textColor=A3_MUTED,
        alignment=TA_CENTER,
        fontName="Helvetica",
        spaceAfter=60,
    )
    flowables.append(Paragraph("A-Cubed Semiconductor Systems Inc.", tagline_style))

    flowables.append(Paragraph("CET Training Manual", styles["title"]))
    flowables.append(
        Paragraph(
            "Critical Environment Technician &mdash; Operations Reference", styles["subtitle"]
        )
    )
    flowables.append(Spacer(1, 0.6 * inch))

    meta_style = ParagraphStyle(
        "covermeta",
        fontSize=11,
        textColor=A3_TEXT,
        alignment=TA_CENTER,
        fontName="Helvetica",
        spaceAfter=4,
        leading=16,
    )
    flowables.append(Paragraph("<b>Facility:</b> A3-Alpha Toronto Area", meta_style))
    flowables.append(
        Paragraph("<b>Classification:</b> Tier IV 2N &mdash; 40 MW hyperscale", meta_style)
    )
    flowables.append(
        Paragraph("<b>Equipment:</b> 118 &times; NVIDIA GB200 NVL72 Blackwell racks", meta_style)
    )
    flowables.append(Paragraph("<b>Author:</b> W. Angel, CTO &amp; Lead Architect", meta_style))

    flowables.append(Spacer(1, 1.0 * inch))
    flowables.append(
        Paragraph(f"Revision 2026.1  |  {datetime.utcnow().strftime('%B %Y')}", styles["meta"])
    )
    flowables.append(PageBreak())
    return flowables


def build_executive_summary(styles, doc_count):
    flowables = [Paragraph("Executive Summary", styles["h1"])]
    flowables.append(
        Paragraph(
            "This manual consolidates the operational knowledge base for "
            "A-Cubed Semiconductor Systems Inc.'s flagship facility, "
            "A3-Alpha Toronto Area. It is the authoritative reference for "
            "Critical Environment Technicians (CETs), facility engineers, "
            "and Network Operations Center (NOC) personnel.",
            styles["body"],
        )
    )
    flowables.append(Spacer(1, 0.1 * inch))
    flowables.append(
        Paragraph(
            f"The manual is organized into four tiers totaling {doc_count} "
            "procedures, standards, and operational references. The tier "
            "structure reflects priority: Tier 1 (Safety) takes absolute "
            "precedence, followed by Tier 2 (Vendor), Tier 3 (Standards), "
            "and Tier 4 (a3semi-specific MOPs/EOPs).",
            styles["body"],
        )
    )
    flowables.append(Spacer(1, 0.1 * inch))
    flowables.append(
        Paragraph(
            "All procedures in this manual are indexed into the DC-EPMS PRO "
            "AI assistant (ChromaDB retrieval-augmented generation with "
            "tier-aware priority scoring). Operators can query the assistant "
            "during incidents for grounded, citation-backed guidance.",
            styles["body"],
        )
    )

    flowables.append(Spacer(1, 0.2 * inch))
    flowables.append(Paragraph("Facility overview", styles["h2"]))

    facility_data = [
        [
            Paragraph("<b>Parameter</b>", styles["tblcell"]),
            Paragraph("<b>Value</b>", styles["tblcell"]),
        ],
        [
            Paragraph("Design tier", styles["tblcell"]),
            Paragraph("Uptime Institute Tier IV, 2N topology", styles["tblcell"]),
        ],
        [
            Paragraph("IT capacity", styles["tblcell"]),
            Paragraph("40 MW (designed), 16.8 MW (current IT load)", styles["tblcell"]),
        ],
        [
            Paragraph("Rack deployment", styles["tblcell"]),
            Paragraph("118 &times; NVIDIA GB200 NVL72 Blackwell (142 kW each)", styles["tblcell"]),
        ],
        [
            Paragraph("PUE target", styles["tblcell"]),
            Paragraph("1.10&ndash;1.15 (typical), &lt;1.30 upper limit", styles["tblcell"]),
        ],
        [
            Paragraph("Cooling", styles["tblcell"]),
            Paragraph("Direct Liquid Cooling + CRAH (95/5 split)", styles["tblcell"]),
        ],
        [
            Paragraph("Emergency power", styles["tblcell"]),
            Paragraph("NFPA 110 Type 10 Level 1 (2x 2.5 MW generators)", styles["tblcell"]),
        ],
        [
            Paragraph("BCDR", styles["tblcell"]),
            Paragraph("ISO 22301 Priority 1 (RTO 15 min, RPO 0)", styles["tblcell"]),
        ],
    ]
    facility_tbl = Table(facility_data, colWidths=[2 * inch, 4.5 * inch])
    facility_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), A3_SLATE),
                ("GRID", (0, 0), (-1, -1), 0.5, A3_MUTED),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flowables.append(facility_tbl)
    flowables.append(PageBreak())
    return flowables


def build_tier_section(tier, docs, styles):
    flowables = []
    tier_color = TIER_COLORS.get(tier, A3_CYAN)

    tier_page_style = ParagraphStyle(
        "tier_page",
        fontSize=56,
        textColor=tier_color,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    flowables.append(Spacer(1, 1.8 * inch))
    flowables.append(Paragraph(f"Tier {tier}", tier_page_style))
    flowables.append(Paragraph(TIER_NAMES.get(tier, f"Tier {tier}"), styles["title"]))
    flowables.append(Spacer(1, 0.4 * inch))
    flowables.append(Paragraph(TIER_DESCRIPTIONS.get(tier, ""), styles["tier_desc"]))
    flowables.append(Spacer(1, 0.3 * inch))
    flowables.append(
        Paragraph(f"This tier contains {len(docs)} procedures/references.", styles["meta"])
    )
    flowables.append(PageBreak())

    for meta, body in docs:
        doc_id = meta.get("doc_id", "UNKNOWN")
        priority = meta.get("priority", "medium")
        standard = meta.get("standard", meta.get("standard_refs", ""))
        if isinstance(standard, list):
            standard = ", ".join(str(s) for s in standard)

        flowables.append(Paragraph(doc_id, styles["h1"]))
        header_meta = f"<b>Tier {tier}</b> &middot; Priority: <b>{priority.upper()}</b>"
        if standard:
            header_meta += f" &middot; Standard: <b>{escape_html(standard)}</b>"
        flowables.append(Paragraph(header_meta, styles["meta"]))

        for fl in md_to_flowables(body, styles):
            flowables.append(fl)

        flowables.append(Spacer(1, 0.3 * inch))
        flowables.append(PageBreak())

    return flowables


def build_toc(tier_docs, styles):
    flowables = [Paragraph("Table of Contents", styles["h1"])]
    flowables.append(Spacer(1, 0.2 * inch))

    toc_data = [
        [
            Paragraph("<b>Tier</b>", styles["tblcell"]),
            Paragraph("<b>Doc ID</b>", styles["tblcell"]),
            Paragraph("<b>Priority</b>", styles["tblcell"]),
            Paragraph("<b>Standard</b>", styles["tblcell"]),
        ]
    ]
    for tier in [1, 2, 3, 4]:
        for meta, _ in tier_docs.get(tier, []):
            doc_id = meta.get("doc_id", "")
            priority = meta.get("priority", "")
            standard = meta.get("standard", meta.get("standard_refs", ""))
            if isinstance(standard, list):
                standard = ", ".join(str(s) for s in standard)
            toc_data.append(
                [
                    Paragraph(f"T{tier}", styles["tblcell"]),
                    Paragraph(escape_html(doc_id), styles["tblcell"]),
                    Paragraph(priority, styles["tblcell"]),
                    Paragraph(escape_html(standard[:60]) if standard else "", styles["tblcell"]),
                ]
            )

    toc_tbl = Table(
        toc_data,
        colWidths=[0.5 * inch, 2.5 * inch, 0.8 * inch, 2.7 * inch],
    )
    toc_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), A3_SLATE),
                ("TEXTCOLOR", (0, 0), (-1, 0), A3_CYAN),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, A3_MUTED),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    flowables.append(toc_tbl)
    flowables.append(PageBreak())
    return flowables


def main():
    print("a3semi CET Training Manual - PDF Generator")
    print("=" * 60)

    if not CORPUS_ROOT.exists():
        print(f"ERROR: Corpus not found at {CORPUS_ROOT}")
        sys.exit(1)

    tier_docs = {1: [], 2: [], 3: [], 4: []}
    total = 0

    for md_path in sorted(CORPUS_ROOT.rglob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        if not meta.get("doc_id"):
            continue
        tier = meta.get("tier", 4)
        if not isinstance(tier, int):
            try:
                tier = int(tier)
            except (ValueError, TypeError):
                tier = 4
        tier_docs.setdefault(tier, []).append((meta, body))
        total += 1
        print(f"  Loaded: T{tier} {meta['doc_id']}")

    print(f"Total documents: {total}")
    print("=" * 60)
    print("Building PDF...")

    styles = build_styles()

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="a3semi CET Training Manual",
        author="W. Angel, a3semi CTO",
    )

    flowables = []
    flowables.extend(build_cover(styles))
    flowables.extend(build_executive_summary(styles, total))
    flowables.extend(build_toc(tier_docs, styles))

    for tier in [1, 2, 3, 4]:
        if tier_docs.get(tier):
            flowables.extend(build_tier_section(tier, tier_docs[tier], styles))

    doc.build(
        flowables,
        onFirstPage=draw_page_background,
        onLaterPages=draw_page_background,
    )

    size_kb = OUTPUT_PDF.stat().st_size // 1024
    print(f"\nGenerated: {OUTPUT_PDF}")
    print(f"Size: {size_kb} KB")
    print(f"Documents: {total}")


if __name__ == "__main__":
    main()
