"""FastAPI 서버 (API 전용). 실행: uvicorn app.main:app --reload --port 8000

화면은 frontend/ (React + Vite)가 맡는다. 개발 중에는 Vite가 /api 요청을 여기로 프록시한다.
응답 형식은 app/api_models.py가 정하고, docs/openapi.json으로 export된다.
"""
import os
from collections import Counter
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import search, store, watch
from .api_models import (AskResult, Briefing, BriefingRequest, NameCount, Ok, Query, RelatedGroup,
                         ReindexResult, ReportDetail, ReportSummary, SearchGroup, Stats, TrainingFinding,
                         UploadResult)
from .pipeline import ingest_bytes, mark_interrupted, process
from .schema import Scenario
from .verify import verify_evidence

load_dotenv()


@asynccontextmanager
async def lifespan(_app):
    mark_interrupted()
    stop = watch.start(os.environ["INBOX_DIR"]) if os.getenv("INBOX_DIR") else None
    yield
    if stop:
        stop.set()


app = FastAPI(title="사고사례 판단 훈련 API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _need(rid: str, name: str):
    obj = store.read(rid, name)
    if obj is None:
        raise HTTPException(404, f"{name} 없음")
    return obj


@app.get("/api/health", response_model=Ok, tags=["system"])
def health():
    return Ok()


# ---------- 보고서 ----------

@app.post("/api/reports", response_model=UploadResult, tags=["reports"])
async def upload(file: UploadFile, bg: BackgroundTasks):
    """PDF 업로드. 처리는 백그라운드로 돌고, 진행 상태는 GET /api/reports/{id}의 status.state로 본다."""
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "PDF 파일만 올릴 수 있습니다")
    rid, is_new = ingest_bytes(data, file.filename or "report.pdf")
    if is_new:
        bg.add_task(process, rid)
    return UploadResult(id=rid, new=is_new)


@app.get("/api/reports", response_model=list[ReportSummary], tags=["reports"])
def list_reports():
    """새로 접수된 순(ingested_at 내림차순)."""
    out = []
    for rid in store.list_ids():
        rec = store.read(rid, "record") or {}
        st = store.read(rid, "status") or {}
        out.append(ReportSummary(
            id=rid, status=st, title=rec.get("title") or st.get("filename", rid),
            report_no=rec.get("report_no", ""), accident_type=rec.get("accident_type", ""),
            occurred_at=rec.get("occurred_at", ""), ingested_at=st.get("ingested_at", ""),
        ))
    return sorted(out, key=lambda x: x.ingested_at, reverse=True)


@app.get("/api/reports/{rid}", response_model=ReportDetail, tags=["reports"])
def get_report(rid: str):
    return ReportDetail(status=_need(rid, "status"), record=store.read(rid, "record"))


@app.get("/api/reports/{rid}/pdf", tags=["reports"], response_class=FileResponse)
def get_pdf(rid: str):
    """원문 PDF. 근거 쪽으로 바로 가려면 프론트에서 #page=N을 붙여 연다."""
    p = store.DATA_DIR / rid / "report.pdf"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


@app.get("/api/reports/{rid}/related", response_model=list[RelatedGroup], tags=["reports"])
def get_related(rid: str):
    """이 사고와 비슷한 과거 사고 + 반복된 규정. 보고서가 늘면 결과도 바뀌도록 매번 계산한다."""
    _need(rid, "record")
    return search.related(rid)


@app.post("/api/reports/{rid}/compare", response_model=AskResult, tags=["reports"])
def compare(rid: str):
    """과거 사고와의 공통점을 LLM이 검색 결과만 근거로 요약."""
    rec = _need(rid, "record")
    return search.ask("다음 사고와 비슷한 과거 사고의 공통 원인과 반복된 권고:\n" + search.record_query(rec), exclude=rid)


# ---------- 판단 훈련 시나리오 ----------

@app.get("/api/reports/{rid}/scenario", response_model=Scenario, tags=["scenario"])
def get_scenario(rid: str):
    return _need(rid, "scenario")


@app.put("/api/reports/{rid}/scenario", response_model=Scenario, tags=["scenario"])
def update_scenario(rid: str, body: Scenario):
    """교관이 고친 시나리오 저장. 저장하면 review_status는 '검수 전'으로 되돌린다.
    각 단계의 answer_id가 그 단계 선택지 id 중 하나가 아니면 422."""
    _need(rid, "status")
    problems = []
    for n, step in enumerate(body.steps, start=1):
        ids = [o.id for o in step.options]
        if len(set(ids)) != len(ids):
            problems.append(f"{n}단계: 선택지 id가 겹침 ({', '.join(ids)})")
        if step.answer_id not in ids:
            problems.append(f"{n}단계: 정답 '{step.answer_id}'이(가) 선택지 id({', '.join(ids)})에 없음")
    if problems:
        raise HTTPException(422, "; ".join(problems))
    body.review_status = "검수 전"
    parsed = store.read(rid, "parsed")
    if parsed:
        verify_evidence(body, parsed.get("pages", []))
    store.write(rid, "scenario", body.model_dump())
    return body


@app.post("/api/reports/{rid}/scenario/regenerate", response_model=Ok, tags=["scenario"])
def regenerate(rid: str, bg: BackgroundTasks):
    _need(rid, "record")
    store.set_status(rid, "queued", "시나리오 다시 생성 대기 중")
    bg.add_task(process, rid, True)
    return Ok()


@app.post("/api/reports/{rid}/scenario/review", response_model=Ok, tags=["scenario"])
def mark_reviewed(rid: str):
    sc = _need(rid, "scenario")
    sc["review_status"] = "검수 완료"
    store.write(rid, "scenario", sc)
    return Ok()


# ---------- 검색·분석 ----------

@app.get("/api/stats", response_model=Stats, tags=["analysis"])
def stats():
    """여러 보고서에 걸친 반복 패턴: 사고유형, 지적된 규정, 교육 관련 지적."""
    types, rules, training = Counter(), Counter(), []
    n = 0
    for rid in store.list_ids():
        rec = store.read(rid, "record")
        if not rec:
            continue
        n += 1
        types[rec.get("accident_type", "기타")] += 1
        for r in rec.get("violated_rules", []):
            rules[r["rule_name"].strip()] += 1
        for t in rec.get("training_findings", []):
            training.append(TrainingFinding(report_id=rid, report=rec.get("title", rid), text=t["text"]))
    return Stats(
        reports=n,
        accident_types=[NameCount(name=k, count=v) for k, v in types.most_common()],
        violated_rules=[NameCount(name=k, count=v) for k, v in rules.most_common(20)],
        training_findings=training,
    )


@app.post("/api/search", response_model=list[SearchGroup], tags=["analysis"])
def similar(body: Query):
    """상황 설명 -> 비슷한 과거 사고 (LLM 없이 검색만)."""
    return search.search(body.q)


@app.post("/api/ask", response_model=AskResult, tags=["analysis"])
def ask(body: Query):
    """검색 결과를 근거로 LLM이 요약 (반복 원인, 확인할 점)."""
    return search.ask(body.q)


@app.post("/api/briefing", response_model=Briefing, tags=["analysis"])
def briefing(body: BriefingRequest):
    """[backlog BE-3] 작업 전 안전 브리핑(TBM) 1장: 비슷한 과거 사고 + 권고 기반 확인 항목."""
    raise HTTPException(501, "아직 구현 전 (docs/backlog.md BE-3)")


@app.post("/api/reindex", response_model=ReindexResult, tags=["system"])
def reindex():
    n = {rid: search.index_report(rid) for rid in store.list_ids() if store.read(rid, "record")}
    return ReindexResult(indexed=n)
