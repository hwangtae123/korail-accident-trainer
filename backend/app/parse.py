"""사조위 철도 사고조사보고서 PDF -> 쪽 번호가 붙은 텍스트 + 목차 기준 섹션.

PDF 읽기는 레이아웃 파서(저장소의 parser/, app/layout_parser.py)가 맡는다. 이 파일은
1) 텍스트 레이어가 없는 PDF를 미리 걸러내고 (OCR 필요)
2) 레이아웃 파서를 부르고
3) 제목 트리에서 못 찾은 섹션만 정규식(split_sections)으로 채운다.

보고서 목차는 대체로 표준화돼 있다:
  개요 -> 1. 사실정보 -> 2. 분석 -> 3. 결론 (3.1 조사결과, 3.2 사고원인) -> 4. 안전권고
목차 페이지에도 같은 제목이 나오므로, 같은 제목이 여러 번 나오면 마지막(본문) 위치를 쓴다.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

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
    """파서를 돌리기 전에 텍스트 레이어가 있는지 빠르게 본다.
    글자를 도형으로 그린 PDF는 파서(pdfplumber)가 쪽마다 선 수만 개를 해석하느라 몇 분씩 걸리기 때문."""
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
    """텍스트 레이어 확인 -> 레이아웃 파서 (쪽별 글자 + 제목 트리 섹션) -> 트리가 못 찾은 섹션은 정규식으로.
    레이아웃 파서가 실패하면 LayoutParserError (처리 상태 error + 이유)."""
    from .layout_parser import parse_with_layout

    pdf_path = Path(pdf_path).resolve()
    quick_text_check(pdf_path)
    pages, tree_sections = parse_with_layout(pdf_path)
    sections = {**split_sections(pages), **tree_sections}
    chars = sum(len(re.sub(r"\s|\[p\.\d+\]", "", p)) for p in pages)
    if chars / max(1, len(pages)) < MIN_CHARS_PER_PAGE:
        raise NeedsOCR(f"텍스트 레이어 없음 (쪽당 {chars // max(1, len(pages))}자)")
    return ParsedReport(pages=pages, sections=sections)
