"""사조위 철도 사고조사보고서 PDF -> 쪽 번호가 붙은 텍스트 + 목차 기준 섹션.

보고서 목차는 대체로 표준화돼 있다:
  개요 -> 1. 사실정보 -> 2. 분석 -> 3. 결론 (3.1 조사결과, 3.2 사고원인) -> 4. 안전권고
목차 페이지에도 같은 제목이 나오므로, 같은 제목이 여러 번 나오면 마지막(본문) 위치를 쓴다.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

# HWP에서 변환된 PDF는 글자 간격이 들쭉날쭉해서 기본값(3)이면 숫자·괄호가 떨어져 나온다.
X_TOLERANCE = 1.5

SECTION_PATTERNS = {
    "facts": r"^\s*1\s*\.\s*사\s*실\s*정\s*보",
    "timeline": r"^\s*1\s*\.\s*1\s*\.?\s*\S*\s*경\s*위",
    "_timeline_end": r"^\s*1\s*\.\s*2\s*\.?\s",  # 경위 다음 소절(1.2)에서 경위를 끊기 위한 경계
    "analysis": r"^\s*2\s*\.\s*분\s*석",
    "conclusion": r"^\s*3\s*\.\s*결\s*론",
    "findings": r"^\s*3\s*\.\s*1\s*\.?\s*조\s*사\s*결\s*과",
    "causes": r"^\s*3\s*\.\s*2\s*\.?\s*사\s*고\s*원\s*인",
    "recommendations": r"^\s*4\s*\.\s*안\s*전\s*권\s*고",
}


MIN_CHARS_PER_PAGE = 50  # 이보다 적으면 글자가 도형으로 그려진(스캔/아웃라인) PDF로 본다


class NeedsOCR(Exception):
    """텍스트 레이어가 없어서 OCR 없이는 내용을 읽을 수 없는 PDF."""


@dataclass
class ParsedReport:
    pages: list[str]
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n".join(self.pages)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    # "( 3 )" -> "(3)", "제 12 조" -> "제12조"
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"제\s+(\d+)\s*조", r"제\1조", text)
    return text.strip()


# 쪽 아래 가운데의 숫자만 있는 줄은 쪽번호로 보고 뺀다 (약관 파서 pdf_lines.mark_page 규칙과 같은 생각).
# "- 12 -" 같은 모양도 포함.
PAGE_NUMBER_RE = re.compile(r"^[-–\s]*\d{1,3}[-–\s]*$")
PAGE_NUMBER_CENTER_TOL = 40  # pt
MAX_OBJS_FOR_TABLES = 3000


def _table_md(rows: list[list]) -> str:
    rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _drop_page_number(page, body) -> str:
    words = body.extract_words(x_tolerance=X_TOLERANCE)
    if not words:
        return ""
    bottom = max(w["bottom"] for w in words)
    last = [w for w in words if abs(w["bottom"] - bottom) < 2]
    text = " ".join(w["text"] for w in last)
    cx = (min(w["x0"] for w in last) + max(w["x1"] for w in last)) / 2
    if PAGE_NUMBER_RE.match(text) and abs(cx - page.width / 2) <= PAGE_NUMBER_CENTER_TOL:
        body = body.crop((0, 0, page.width, min(w["top"] for w in last) - 0.5))
    return body.extract_text(x_tolerance=X_TOLERANCE) or ""


def extract_pages(pdf_path: str | Path) -> list[str]:
    """PDF -> 쪽별 텍스트 목록. 각 원소는 "[p.N]\\n본문" 형식이어야 한다.

    표는 본문에서 빼서 Markdown 표로 쪽 끝에 붙인다 (본문에 표 글자가 섞이면 문장이 깨진다).
    ※ 약관 파서(pdfplumber-body-table-parser)의 표 추출로 바꿔 끼우려면 이 함수만 고치면 된다.
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            # 글자를 도형으로 그린 쪽(텍스트 레이어 없음)이나 도면 쪽은 선이 수만 개라 표 감지가 멈춘다 -> 건너뜀
            n_objs = len(page.lines) + len(page.rects) + len(page.curves)
            tables = [t for t in page.find_tables() if len(t.rows) >= 2] if n_objs <= MAX_OBJS_FOR_TABLES else []
            bboxes = [t.bbox for t in tables]

            def outside_tables(obj, bboxes=bboxes):
                if obj.get("object_type") != "char":
                    return True
                cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
                return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in bboxes)

            body = page.filter(outside_tables) if bboxes else page
            text = _clean(_drop_page_number(page, body))
            for k, t in enumerate(tables, start=1):
                md = _table_md(t.extract(x_tolerance=X_TOLERANCE))
                if md:
                    text += f"\n\n[표 p.{i}-{k}]\n{md}"
            pages.append(f"[p.{i}]\n{text}")
    return pages


def split_sections(pages: list[str]) -> dict[str, str]:
    """각 섹션의 시작 줄을 찾아 다음 섹션 시작 전까지 자른다."""
    lines = "\n".join(pages).split("\n")
    starts: dict[str, int] = {}
    for name, pat in SECTION_PATTERNS.items():
        hits = [i for i, line in enumerate(lines) if re.match(pat, line)]
        if hits:
            starts[name] = hits[-1]  # 목차 말고 본문 쪽

    # 쪽 표시([p.N])를 잃지 않도록, 섹션 시작 직전의 쪽 표시를 앞에 붙인다.
    def page_marker_before(idx: int) -> str:
        for j in range(idx, -1, -1):
            if lines[j].startswith("[p."):
                return lines[j]
        return ""

    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    sections = {}
    for name, start in ordered:
        if name.startswith("_"):
            continue
        # 같은 수준 이상의 다음 섹션에서 끝낸다 (하위 섹션은 상위 섹션 안에 포함)
        later = [s for n, s in ordered if s > start and not _is_child(n, name)]
        end = min(later) if later else len(lines)
        body = "\n".join(lines[start:end])
        marker = page_marker_before(start)
        sections[name] = f"{marker}\n{body}" if marker and not body.startswith("[p.") else body
    return sections


_CHILDREN = {"facts": {"timeline", "_timeline_end"}, "conclusion": {"findings", "causes"}}


def _is_child(candidate: str, parent: str) -> bool:
    return candidate in _CHILDREN.get(parent, set())


def quick_text_check(pdf_path: str | Path, sample: int = 6) -> None:
    """pdfplumber로 읽기 전에 텍스트 레이어가 있는지 빠르게 본다.
    글자를 도형으로 그린 PDF는 pdfplumber가 쪽마다 선 수만 개를 해석하느라 몇 분씩 걸리기 때문."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        n = len(doc)
        idx = sorted({int(i * (n - 1) / max(1, sample - 1)) for i in range(min(sample, n))})
        chars = 0
        for i in idx:
            tp = doc[i].get_textpage()
            chars += len(re.sub(r"\s", "", tp.get_text_range()))
            tp.close()
    finally:
        doc.close()
    if chars / max(1, len(idx)) < MIN_CHARS_PER_PAGE:
        raise NeedsOCR(f"텍스트 레이어 없음 (표본 쪽당 {chars // max(1, len(idx))}자)")


def parse_report(pdf_path: str | Path) -> ParsedReport:
    quick_text_check(pdf_path)
    pages = extract_pages(pdf_path)
    chars = sum(len(re.sub(r"\s|\[p\.\d+\]", "", p)) for p in pages)
    if chars / max(1, len(pages)) < MIN_CHARS_PER_PAGE:
        raise NeedsOCR(f"텍스트 레이어 없음 (쪽당 {chars // max(1, len(pages))}자)")
    return ParsedReport(pages=pages, sections=split_sections(pages))
