"""작업 전 안전 브리핑 TBM (backlog BE-3).

오늘 작업 설명 -> 유사사고 검색 3건 -> 그 보고서들의 안전권고·기여요인만 LLM에 주고 summary + checklist를 만든다.
- LLM에는 항목마다 번호(예: R2-3)를 붙여 주고, checklist 항목은 그 번호로 출처를 밝히게 한다.
- 코드가 번호를 원래 항목으로 되돌려 source_report_id·source_title·evidence를 채운다.
  번호가 없거나 검색된 보고서가 아닌 항목은 버린다 (근거 없는 확인 항목을 만들지 않기 위해).
"""
from pydantic import BaseModel, Field

from . import search, store
from .api_models import Briefing, ChecklistItem, SearchGroup
from .llm import complete_json
from .schema import Evidence

N_REPORTS = 3
MAX_ITEMS_PER_REPORT = 20

BRIEFING_SYSTEM = """당신은 철도 현장 작업책임자의 작업 전 안전 브리핑(TBM)을 돕는 안전 담당자입니다.
오늘 작업 설명과, 비슷한 과거 사고조사보고서의 안전권고·기여요인 항목이 번호와 함께 주어집니다.
규칙:
- 주어진 항목에 있는 내용만 쓰세요. 없는 사실·수치·규정을 만들지 마세요.
- summary: 비슷한 과거 사고가 무엇이었고 공통 원인이 무엇인지 3~5문장. 문장마다 [보고서 제목 p.N] 근거를 붙이세요 (쪽 번호가 없으면 제목만).
- checklist: 오늘 작업 시작 전에 현장에서 확인할 항목 3~8개. 각 항목은 "~했는가?"처럼 현장에서 바로 확인할 수 있는 짧은 문장.
  각 항목의 source_item에는 근거가 된 항목 번호(예: R1-2)를 정확히 하나 넣고, source_report_id에는 그 항목의 보고서 id를 넣으세요.
- 오늘 작업과 관련 없는 항목은 고르지 마세요. 관련 있는 항목이 없으면 checklist를 비우고 summary에 그렇다고 쓰세요."""


class _DraftItem(BaseModel):
    text: str
    source_item: str = Field(description="근거 항목 번호 (예: R1-2)")
    source_report_id: str


class _Draft(BaseModel):
    summary: str
    checklist: list[_DraftItem] = Field(default_factory=list)


def _candidates(groups: list[dict]) -> tuple[dict[str, dict], str]:
    """검색된 보고서들의 안전권고·기여요인 -> ({번호: 항목}, LLM 입력 문자열)."""
    items: dict[str, dict] = {}
    lines: list[str] = []
    for r, g in enumerate(groups, start=1):
        rec = store.read(g["report_id"], "record") or {}
        title = rec.get("title") or g["title"]
        lines.append(f"## 보고서 R{r}: {title} (id: {g['report_id']}, 유형: {rec.get('accident_type', '')}, "
                     f"발생: {rec.get('occurred_at', '')})")
        entries = [("안전권고", x, f"[{x.get('target', '')}] " if x.get("target") else "")
                   for x in rec.get("recommendations", [])]
        entries += [("기여요인", x, "") for x in rec.get("contributing_factors", [])]
        for k, (kind, x, prefix) in enumerate(entries[:MAX_ITEMS_PER_REPORT], start=1):
            key = f"R{r}-{k}"
            ev = x.get("evidence") or {}
            items[key] = {"report_id": g["report_id"], "title": title, "evidence": ev}
            pg = f" p.{ev['page']}" if ev.get("page") else ""
            lines.append(f"- {key} ({kind}{pg}) {prefix}{x.get('text', '')}")
    return items, "\n".join(lines)


def build(work: str) -> Briefing:
    groups = search.search(work, n_reports=N_REPORTS, hits_per_report=3)
    similar = [SearchGroup(**g) for g in groups]
    if not groups:
        return Briefing(work=work, summary="", checklist=[], similar=[])

    items, ctx = _candidates(groups)
    if not items:  # 검색된 보고서에 안전권고·기여요인이 하나도 없으면 LLM을 부르지 않는다
        return Briefing(work=work, summary="비슷한 과거 사고의 안전권고·기여요인을 찾지 못했습니다.",
                        checklist=[], similar=similar)

    draft = complete_json(BRIEFING_SYSTEM, f"## 오늘 작업\n{work}\n\n## 과거 사고 항목\n{ctx}", _Draft)
    allowed = {g["report_id"] for g in groups}
    checklist, seen = [], set()
    for d in draft.checklist:
        src = items.get(d.source_item.strip().upper())
        if not src or src["report_id"] not in allowed or d.source_report_id != src["report_id"]:
            continue  # 출처를 확인할 수 없는 항목은 버린다
        if d.text in seen:
            continue
        seen.add(d.text)
        checklist.append(ChecklistItem(text=d.text, source_report_id=src["report_id"], source_title=src["title"],
                                       evidence=Evidence(**src["evidence"])))
    return Briefing(work=work, summary=draft.summary, checklist=checklist, similar=similar)
