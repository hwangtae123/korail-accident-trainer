"""FastAPI 서버 (API 전용). 실행: uvicorn app.main:app --reload --port 8000

화면은 frontend/ (React + Vite)가 맡는다. 개발 중에는 Vite가 /api 요청을 여기로 프록시한다.
응답 형식은 app/api_models.py가 정하고, docs/openapi.json으로 export된다.
"""
import os
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

from . import briefing as briefing_mod
from . import search, store, watch
from .api_models import (AskResult, Briefing, BriefingRequest, NameCount, Ok, Query, RelatedGroup,
                         ReindexResult, ReportDetail, ReportSummary, SearchGroup, Stats, TrainingFinding,
                         UploadResult, FigureMeta, AppConfig, UploadUrlRequest, UploadUrlResult, ProcessRequest, ReportStatus)
from .llm import LLMError
from .pipeline import BUSY, heal, in_request, ingest_bytes, mark_interrupted, process, reprocessable
from .rule_aliases import canonical_key
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
    # 화면을 다른 주소(Vercel)에 두면 그 주소를 허용한다. CORS_ORIGINS: 쉼표로 구분한 정확한 주소,
    # CORS_ORIGIN_REGEX: 미리보기 배포처럼 바뀌는 주소 (예: https://accident-trainer(-[a-z0-9-]+)?\.vercel\.app)
    allow_origins=[o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(LLMError)
async def llm_failed(_request, e: LLMError):
    """요약·브리핑처럼 바로 LLM을 부르는 API가 실패하면 502와 이유를 돌려준다 (화면에 그대로 보여 줌)."""
    return JSONResponse(status_code=502, content={"detail": f"LLM 호출 실패 — {e}"})


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
        if in_request():  # 서버리스: 응답 뒤 작업이 보장되지 않으므로 요청 안에서 끝낸다
            await run_in_threadpool(process, rid)
        else:
            bg.add_task(process, rid)
    return UploadResult(id=rid, new=is_new)


MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))


@app.get("/api/config", response_model=AppConfig, tags=["system"])
def config():
    """화면이 업로드 방식을 고른다. Supabase를 쓰면 PDF를 Storage에 직접 올린다 (서버리스 함수의 요청 크기 제한을 피함)."""
    return AppConfig(direct_upload=store.backend() == "supabase", max_upload_mb=MAX_UPLOAD_MB)


@app.post("/api/reports/upload-url", response_model=UploadUrlResult, tags=["reports"])
def upload_url(body: UploadUrlRequest):
    """직접 업로드 1단계: 같은 파일이 이미 있으면 new=false. 아니면 Storage에 PUT할 1회용 주소를 준다.
    다음: 그 주소로 PDF를 PUT -> POST /api/reports/{id}/process."""
    if store.backend() != "supabase":
        raise HTTPException(400, "직접 업로드는 Supabase 저장소에서만 쓴다 — POST /api/reports를 쓰세요")
    st = heal(body.id, store.read(body.id, "status")) or {}
    if not reprocessable(st):
        return UploadUrlResult(id=body.id, new=False)
    from . import supa_storage

    url = supa_storage.signed_upload_url(f"{body.id}/{store.PDF_NAME}")
    store.set_status(body.id, "queued", "PDF 올리는 중", filename=body.filename or "report.pdf", uploading=True)
    return UploadUrlResult(id=body.id, new=True, upload_url=url)


@app.post("/api/reports/{rid}/process", response_model=ReportStatus, tags=["reports"])
def process_uploaded(rid: str, body: ProcessRequest):
    """직접 업로드 2단계: Storage에 올라간 PDF를 확인(PDF인지, 내용 해시가 id와 같은지)하고 끝까지 처리한다.
    서버리스에서는 이 요청 안에서 처리한다 (1~2분). 화면은 이 응답을 기다리지 않고 GET /api/reports/{id}로 진행을 본다."""
    st = _need(rid, "status")
    if st.get("state") in BUSY and not st.get("uploading"):
        return st  # 이미 다른 요청이 처리 중
    if st.get("state") == "done" or (st.get("state") == "ocr_needed" and not reprocessable(st)):
        return st
    from . import supa_storage

    data = supa_storage.download(f"{rid}/{store.PDF_NAME}")
    if data is None:
        store.set_status(rid, "error", "올린 PDF를 찾을 수 없습니다 — 다시 올려주세요")
        raise HTTPException(404, "Storage에 PDF가 없습니다")
    if not data.startswith(b"%PDF") or store.report_id(data) != rid:
        store.set_status(rid, "error", "올린 파일이 PDF가 아니거나 내용이 id와 다릅니다 — 다시 올려주세요")
        raise HTTPException(400, "PDF가 아니거나 내용 해시가 id와 다릅니다")
    (store.rdir(rid) / store.PDF_NAME).write_bytes(data)  # 파서가 읽을 로컬 사본 (Storage에는 이미 있음)
    store.set_status(rid, "queued", "대기 중", filename=body.filename or None)
    process(rid)
    return store.read(rid, "status")


@app.get("/api/reports", response_model=list[ReportSummary], tags=["reports"])
def list_reports():
    """새로 접수된 순(ingested_at 내림차순)."""
    out = []
    for rid, docs in store.iter_docs("status", "record"):
        rec = docs["record"] or {}
        st = heal(rid, docs["status"]) or {}
        out.append(ReportSummary(
            id=rid, status=st, title=rec.get("title") or st.get("filename", rid),
            report_no=rec.get("report_no", ""), accident_type=rec.get("accident_type", ""),
            occurred_at=rec.get("occurred_at", ""), ingested_at=st.get("ingested_at", ""),
        ))
    return sorted(out, key=lambda x: x.ingested_at, reverse=True)


@app.get("/api/reports/{rid}", response_model=ReportDetail, tags=["reports"])
def get_report(rid: str):
    return ReportDetail(status=heal(rid, _need(rid, "status")), record=store.read(rid, "record"))


@app.get("/api/reports/{rid}/pdf", tags=["reports"], response_class=FileResponse)
def get_pdf(rid: str):
    """원문 PDF. 근거 쪽으로 바로 가려면 프론트에서 #page=N을 붙여 연다."""
    p = store.local_pdf(rid)
    if p is None:
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


@app.get("/api/reports/{rid}/figures", response_model=list[FigureMeta], tags=["reports"])
def list_figures(rid: str):
    """보고서의 그림·사진 (설명 줄 [그림N] 기준으로 잘라낸 것). 아직 뽑지 않았거나 없으면 빈 목록."""
    _need(rid, "status")
    return [FigureMeta(**{k: m[k] for k in ("n", "page", "label", "caption", "width", "height")},
                       url=f"/api/reports/{rid}/figures/{m['n']}.webp?v={m.get('key', '')}")
            for m in (store.read(rid, "figures") or [])]


@app.get("/api/reports/{rid}/figures/{n}.webp", tags=["reports"], response_class=Response)
def get_figure(rid: str, n: int):
    data = store.read_blob(rid, f"figures/{n}.webp")
    if data is None:
        raise HTTPException(404, "그림 없음")
    # 주소에 내용 해시(?v=)가 붙으므로 오래 캐시해도 된다 (Vercel CDN도 캐시)
    return Response(data, media_type="image/webp",
                    headers={"Cache-Control": "public, max-age=86400, s-maxage=31536000, immutable"})


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
    if in_request():  # 서버리스: 요청 안에서 끝낸다 (화면은 응답을 기다리지 않고 상태를 폴링)
        process(rid, True)
    else:
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
    names: dict[str, Counter] = {}  # 규정 키 -> 실제 표기들 (가장 많이 쓴 표기를 이름으로 보여준다)
    n = 0
    for rid, docs in store.iter_docs("record"):
        rec = docs["record"]
        if not rec:
            continue
        n += 1
        types[rec.get("accident_type", "기타")] += 1
        for key, name in {canonical_key(r["rule_name"]): r["rule_name"].strip()
                          for r in rec.get("violated_rules", [])}.items():  # 한 보고서에서 같은 규정은 1번
            rules[key] += 1
            names.setdefault(key, Counter())[name] += 1
        for t in rec.get("training_findings", []):
            training.append(TrainingFinding(report_id=rid, report=rec.get("title", rid), text=t["text"]))
    return Stats(
        reports=n,
        accident_types=[NameCount(name=k, count=v) for k, v in types.most_common()],
        violated_rules=[NameCount(name=names[k].most_common(1)[0][0], count=v) for k, v in rules.most_common(20)],
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
    """작업 전 안전 브리핑(TBM) 1장: 비슷한 과거 사고 3건 + 그 안전권고·기여요인에서 뽑은 확인 항목.
    확인 항목의 출처는 검색된 보고서로 코드가 검증한다. 색인된 보고서가 없으면 빈 결과."""
    return briefing_mod.build(body.work)


@app.post("/api/reindex", response_model=ReindexResult, tags=["system"])
def reindex():
    n = {rid: search.index_report(rid) for rid, docs in store.iter_docs("record") if docs["record"]}
    return ReindexResult(indexed=n)


# ---------- 화면 (배포용) ----------
# 프론트 빌드(frontend/dist)가 있으면 같은 서버가 "/"에서 내보낸다 (API는 /api/…). 개발 중에는 Vite(5173)를 쓴다.
_dist = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if (_dist / "index.html").exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
