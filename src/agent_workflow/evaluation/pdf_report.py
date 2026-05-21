"""Markdown-to-PDF generation for evaluation reports.

Converts AI-generated Markdown (with tables, headers, bold, lists) into a
styled PDF using the `markdown` library for parsing and `reportlab` for
PDF rendering with full CJK support.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_REPORT_DIR = Path("data/evaluation-reports")
_FONT_REGISTERED = False


def _register_cjk_font() -> str:
    """Register a CJK font and return its name."""
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return "CJK"
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", path))
                _FONT_REGISTERED = True
                return "CJK"
            except Exception:
                continue
    return "Helvetica"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

_COLORS = {
    "primary": HexColor("#1e40af"),
    "primary_light": HexColor("#3b82f6"),
    "bg_section": HexColor("#f0f4ff"),
    "bg_table_header": HexColor("#1e3a5f"),
    "text_dark": HexColor("#1a1a2e"),
    "text_body": HexColor("#2d2d2d"),
    "text_muted": HexColor("#6b7280"),
    "score_pass": HexColor("#166534"),
    "score_fail": HexColor("#dc2626"),
    "border": HexColor("#cbd5e1"),
    "row_alt": HexColor("#f8fafc"),
}


def _build_styles(font_name: str) -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "Title", fontName=font_name, fontSize=18, leading=26,
            spaceAfter=4, textColor=_COLORS["text_dark"], alignment=TA_CENTER,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", fontName=font_name, fontSize=10, leading=14,
            spaceAfter=10, textColor=_COLORS["text_muted"], alignment=TA_CENTER,
        ),
        "h2": ParagraphStyle(
            "H2", fontName=font_name, fontSize=13, leading=19,
            spaceBefore=12, spaceAfter=4, textColor=_COLORS["primary"],
            backColor=_COLORS["bg_section"], borderPadding=(5, 8, 5, 8),
        ),
        "h3": ParagraphStyle(
            "H3", fontName=font_name, fontSize=11, leading=16,
            spaceBefore=8, spaceAfter=3, textColor=HexColor("#1e3a5f"),
        ),
        "body": ParagraphStyle(
            "Body", fontName=font_name, fontSize=10, leading=15,
            spaceAfter=3, textColor=_COLORS["text_body"],
        ),
        "body_indent": ParagraphStyle(
            "BodyIndent", fontName=font_name, fontSize=10, leading=15,
            leftIndent=12, spaceAfter=2, textColor=_COLORS["text_body"],
        ),
        "score_pass": ParagraphStyle(
            "ScorePass", fontName=font_name, fontSize=16, leading=22,
            spaceBefore=2, spaceAfter=2, textColor=_COLORS["score_pass"],
            alignment=TA_CENTER,
        ),
        "score_fail": ParagraphStyle(
            "ScoreFail", fontName=font_name, fontSize=16, leading=22,
            spaceBefore=2, spaceAfter=2, textColor=_COLORS["score_fail"],
            alignment=TA_CENTER,
        ),
        "conclusion_pass": ParagraphStyle(
            "ConclusionPass", fontName=font_name, fontSize=14, leading=20,
            textColor=_COLORS["score_pass"], alignment=TA_CENTER,
        ),
        "conclusion_fail": ParagraphStyle(
            "ConclusionFail", fontName=font_name, fontSize=14, leading=20,
            textColor=_COLORS["score_fail"], alignment=TA_CENTER,
        ),
        "table_header": ParagraphStyle(
            "TableHeader", fontName=font_name, fontSize=9, leading=13,
            textColor=white, alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "TableCell", fontName=font_name, fontSize=9, leading=13,
            textColor=_COLORS["text_body"],
        ),
        "footer": ParagraphStyle(
            "Footer", fontName=font_name, fontSize=8, leading=11,
            textColor=_COLORS["text_muted"], alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# Markdown → Reportlab elements converter
# ---------------------------------------------------------------------------

class _MarkdownToPlatypus:
    """Converts Markdown text to a list of reportlab Platypus flowables."""

    def __init__(self, styles: dict[str, ParagraphStyle]) -> None:
        self.styles = styles

    def convert(self, md_text: str) -> list:
        """Parse Markdown and return flowables."""
        elements: list = []
        lines = md_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Empty line
            if not stripped:
                elements.append(Spacer(1, 4))
                i += 1
                continue

            # Table detection (line with |)
            if "|" in stripped and i + 1 < len(lines) and _is_table_separator(lines[i + 1].strip()):
                table_lines = []
                while i < len(lines) and "|" in lines[i].strip():
                    table_lines.append(lines[i].strip())
                    i += 1
                table = self._build_table(table_lines)
                if table:
                    elements.append(Spacer(1, 4))
                    elements.append(table)
                    elements.append(Spacer(1, 4))
                continue

            # Also detect tables without separator (just pipe-delimited rows)
            if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
                table_lines = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                table = self._build_table(table_lines)
                if table:
                    elements.append(Spacer(1, 4))
                    elements.append(table)
                    elements.append(Spacer(1, 4))
                continue

            # Headers
            if stripped.startswith("# "):
                # H1 — main title, skip (we add our own)
                i += 1
                continue
            if stripped.startswith("## "):
                text = self._inline_format(stripped[3:])
                elements.append(HRFlowable(
                    width="100%", thickness=0.5, color=_COLORS["border"],
                    spaceBefore=8, spaceAfter=2,
                ))
                elements.append(Paragraph(f"<b>{text}</b>", self.styles["h2"]))
                i += 1
                continue
            if stripped.startswith("### "):
                text = self._inline_format(stripped[4:])
                elements.append(Paragraph(f"<b>{text}</b>", self.styles["h3"]))
                i += 1
                continue

            # Legacy 【xxx】 section headers (backwards compatibility)
            if stripped.startswith("【") and "】" in stripped:
                text = self._inline_format(stripped)
                elements.append(HRFlowable(
                    width="100%", thickness=0.5, color=_COLORS["border"],
                    spaceBefore=8, spaceAfter=2,
                ))
                elements.append(Paragraph(f"<b>{text}</b>", self.styles["h2"]))
                i += 1
                continue

            # Horizontal rule
            if stripped in ("---", "***", "___"):
                elements.append(HRFlowable(
                    width="100%", thickness=1, color=_COLORS["primary_light"],
                    spaceBefore=6, spaceAfter=6,
                ))
                i += 1
                continue

            # Score line detection (X / 10 分 or X/10)
            if re.search(r"\d+\.?\d*\s*/\s*10\s*分?", stripped):
                score_match = re.search(r"(\d+\.?\d*)\s*/\s*10", stripped)
                if score_match:
                    score = float(score_match.group(1))
                    style = self.styles["score_pass"] if score >= 8 else self.styles["score_fail"]
                    text = self._inline_format(stripped)
                    elements.append(Paragraph(f"<b>{text}</b>", style))
                    i += 1
                    continue

            # Conclusion line (通过/不通过)
            if stripped in ("通过", "不通过", "**通过**", "**不通过**"):
                clean = stripped.replace("**", "")
                style = self.styles["conclusion_pass"] if "不" not in clean else self.styles["conclusion_fail"]
                elements.append(Paragraph(f"<b>{clean}</b>", style))
                i += 1
                continue

            # Bullet list
            if stripped.startswith("- ") or stripped.startswith("* "):
                text = self._inline_format(stripped[2:])
                elements.append(Paragraph(f"• {text}", self.styles["body_indent"]))
                i += 1
                continue

            # Numbered list
            num_match = re.match(r"^(\d+)\.\s+(.+)", stripped)
            if num_match:
                text = self._inline_format(num_match.group(2))
                elements.append(Paragraph(
                    f"<b>{num_match.group(1)}.</b> {text}", self.styles["body_indent"]
                ))
                i += 1
                continue

            # Blockquote
            if stripped.startswith("> "):
                text = self._inline_format(stripped[2:])
                quote_style = ParagraphStyle(
                    "Quote", parent=self.styles["body"],
                    leftIndent=15, textColor=_COLORS["text_muted"],
                    borderPadding=(2, 4, 2, 4),
                )
                elements.append(Paragraph(f"<i>{text}</i>", quote_style))
                i += 1
                continue

            # Regular paragraph
            text = self._inline_format(stripped)
            elements.append(Paragraph(text, self.styles["body"]))
            i += 1

        return elements

    def _inline_format(self, text: str) -> str:
        """Convert Markdown inline formatting to reportlab XML tags."""
        # Escape XML special chars first (but preserve our tags)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Bold + italic (***text***)
        text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
        # Bold (**text**)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        # Italic (*text*)
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        # Inline code (`text`)
        text = re.sub(r"`(.+?)`", r'<font color="#dc2626" backColor="#f3f4f6">\1</font>', text)
        # Strikethrough (~~text~~)
        text = re.sub(r"~~(.+?)~~", r"<strike>\1</strike>", text)

        return text

    def _build_table(self, table_lines: list[str]) -> Table | None:
        """Parse Markdown table lines into a reportlab Table."""
        if len(table_lines) < 2:
            return None

        # Filter out separator lines (|---|---|)
        data_lines = [l for l in table_lines if not _is_table_separator(l)]
        if not data_lines:
            return None

        # Parse cells
        rows: list[list[str]] = []
        for line in data_lines:
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells)

        if not rows:
            return None

        # Determine column count
        col_count = max(len(row) for row in rows)

        # Normalize rows
        for row in rows:
            while len(row) < col_count:
                row.append("")

        # Build table data with Paragraphs
        table_data: list[list[Any]] = []
        for ri, row in enumerate(rows):
            style = self.styles["table_header"] if ri == 0 else self.styles["table_cell"]
            table_data.append([
                Paragraph(self._inline_format(cell), style)
                for cell in row
            ])

        # Calculate column widths
        page_width = A4[0] - 36 * mm  # Available width
        col_width = page_width / col_count

        table = Table(table_data, colWidths=[col_width] * col_count)

        # Table styling
        style_commands: list = [
            ("BACKGROUND", (0, 0), (-1, 0), _COLORS["bg_table_header"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ("TOPPADDING", (0, 1), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, _COLORS["border"]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]

        # Alternating row colors
        for ri in range(1, len(table_data)):
            if ri % 2 == 0:
                style_commands.append(
                    ("BACKGROUND", (0, ri), (-1, ri), _COLORS["row_alt"])
                )

        table.setStyle(TableStyle(style_commands))
        return table


def _is_table_separator(line: str) -> bool:
    """Check if a line is a Markdown table separator (|---|---|)."""
    cleaned = line.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
    return len(cleaned) == 0 and "-" in line


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_evaluation_pdf(text: str, filename: str = "evaluation.pdf") -> Path:
    """Generate a styled PDF report from Markdown evaluation text.

    The AI model outputs Markdown with:
    - ## headers for sections
    - | tables | for data
    - **bold** for emphasis
    - Numbered/bullet lists
    - Score lines (X / 10 分)
    """
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / filename
    font_name = _register_cjk_font()
    styles = _build_styles(font_name)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    elements: list = []

    # ---- Title block ----
    elements.append(Paragraph(
        "<b>110 实验室课题终期评测报告</b>", styles["title"]
    ))
    elements.append(Paragraph(
        "AI 智能体自动评测 · 仅供参考", styles["subtitle"]
    ))
    elements.append(HRFlowable(
        width="100%", thickness=2, color=_COLORS["primary_light"],
        spaceBefore=2, spaceAfter=10,
    ))

    # ---- Convert Markdown content ----
    converter = _MarkdownToPlatypus(styles)
    content_elements = converter.convert(text)
    elements.extend(content_elements)

    # ---- Footer ----
    elements.append(Spacer(1, 16))
    elements.append(HRFlowable(
        width="100%", thickness=1, color=_COLORS["primary_light"],
        spaceBefore=8, spaceAfter=6,
    ))
    elements.append(Paragraph(
        "本报告由 110 实验室课题评测智能体自动生成。评测基于 AI 工具循环深度分析，"
        "评分标准参照高水平学术实验要求，仅供参考。",
        styles["footer"],
    ))

    doc.build(elements)
    return path
