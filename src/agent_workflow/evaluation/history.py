"""Simple XLSX-backed repository review history."""

import html
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from pydantic import BaseModel

_HEADERS = [
    "仓库链接",
    "课题名称",
    "上次评分",
    "上次评价",
    "更新时间",
    "工具调用摘要",
    "评价次数",
]
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DEFAULT_PATH = Path("data/review-history/repository_reviews.xlsx")


class ReviewHistoryRecord(BaseModel):
    repo_url: str
    topic_name: str
    score: float | None = None
    review: str = ""
    updated_at: str = ""
    tool_summary: str = ""
    review_count: int = 0


class ReviewHistoryUpdateResult(BaseModel):
    updated: bool
    reason: str
    record: ReviewHistoryRecord
    path: str


class ReviewHistoryStore:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self.path = path

    def get(self, repo_url: str) -> ReviewHistoryRecord | None:
        rows = self._read_rows()
        for row in rows[1:]:
            if row and row[0] == repo_url:
                return _row_to_record(row)
        return None

    def update(
        self,
        *,
        repo_url: str,
        topic_name: str,
        review: str,
        score: float | None,
        improved: bool,
        tool_summary: str = "",
    ) -> ReviewHistoryUpdateResult:
        rows = self._read_rows()
        if not rows:
            rows = [_HEADERS]
        existing_index = None
        for index, row in enumerate(rows[1:], start=1):
            if row and row[0] == repo_url:
                existing_index = index
                break
        existing = _row_to_record(rows[existing_index]) if existing_index is not None else None
        if existing is not None and not improved:
            return ReviewHistoryUpdateResult(
                updated=False,
                reason="模型判断相较上次没有明显优化，Excel 未更新。",
                record=existing,
                path=str(self.path),
            )
        record = ReviewHistoryRecord(
            repo_url=repo_url,
            topic_name=topic_name,
            score=score,
            review=review,
            updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            tool_summary=tool_summary,
            review_count=(existing.review_count + 1 if existing else 1),
        )
        row = _record_to_row(record)
        if existing_index is None:
            rows.append(row)
        else:
            rows[existing_index] = row
        self._write_rows(rows)
        return ReviewHistoryUpdateResult(
            updated=True,
            reason="首次记录或模型判断已有明显优化，Excel 已更新。",
            record=record,
            path=str(self.path),
        )

    def _read_rows(self) -> list[list[str]]:
        if not self.path.exists():
            return [_HEADERS]
        try:
            with zipfile.ZipFile(self.path) as archive:
                xml = archive.read("xl/worksheets/sheet1.xml")
        except (OSError, KeyError, zipfile.BadZipFile):
            return [_HEADERS]
        root = ET.fromstring(xml)
        rows: list[list[str]] = []
        for row_el in root.findall(f".//{{{_NS}}}row"):
            values: list[str] = []
            for cell in row_el.findall(f"{{{_NS}}}c"):
                inline = cell.find(f"{{{_NS}}}is/{{{_NS}}}t")
                value = inline.text if inline is not None and inline.text is not None else ""
                values.append(value)
            rows.append(values)
        return rows or [_HEADERS]

    def _write_rows(self, rows: list[list[str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", _content_types_xml())
            archive.writestr("_rels/.rels", _rels_xml())
            archive.writestr("xl/workbook.xml", _workbook_xml())
            archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml())
            archive.writestr("xl/styles.xml", _styles_xml())
            archive.writestr("xl/worksheets/sheet1.xml", _sheet_xml(rows))


def _row_to_record(row: list[str]) -> ReviewHistoryRecord:
    values = [*row, *([""] * max(0, len(_HEADERS) - len(row)))]
    score = _parse_float(values[2])
    return ReviewHistoryRecord(
        repo_url=values[0],
        topic_name=values[1],
        score=score,
        review=values[3],
        updated_at=values[4],
        tool_summary=values[5],
        review_count=int(_parse_float(values[6]) or 0),
    )


def _record_to_row(record: ReviewHistoryRecord) -> list[str]:
    return [
        record.repo_url,
        record.topic_name,
        "" if record.score is None else str(record.score),
        record.review,
        record.updated_at,
        record.tool_summary,
        str(record.review_count),
    ]


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _sheet_xml(rows: list[list[str]]) -> str:
    body = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{_column_name(col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(str(value))}</t></is></c>'
            )
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_NS}" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheetData>{"".join(body)}</sheetData></worksheet>'
    )


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""


def _rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _workbook_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="评审记录" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""


def _workbook_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Arial"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="1"><xf xfId="0"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
