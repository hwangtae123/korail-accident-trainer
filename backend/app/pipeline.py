"""PDF 한 건을 끝까지 처리한다: 파싱 -> 구조화 -> 시나리오. 단계마다 결과를 저장한다.

처리 방식은 둘이다.
- 서버 (로컬·Docker): 업로드에 바로 응답하고 백그라운드에서 처리. 서버가 꺼지면 mark_interrupted가 정리.
- 서버리스 (Vercel, PROCESS_IN_REQUEST=1): 응답 뒤 작업이 보장되지 않으므로 처리 요청 안에서 끝까지 처리.
  함수가 시간 제한(300초)에 걸려 죽으면 '처리 중'에 멈춘 건이 남으므로, 읽을 때 heal()이 오류로 바꾼다.
"""
import os
import re
import traceback
from datetime import datetime

from . import search, store
from .extract import build_scenario, extract_record
from .parse import MIN_HANGUL_PER_PAGE, NeedsOCR, ParsedReport, parse_report, split_sections
from .schema import AccidentRecord
from .verify import verify_evidence


def process(rid: str, only_scenario: bool = False) -> None:
    try:
        if only_scenario:
            parsed = ParsedReport(**store.read(rid, "parsed"))
            record = AccidentRecord(**store.read(rid, "record"))
        else:
            store.set_status(rid, "parsing", "PDF 텍스트 추출 중")
            pdf_path = store.local_pdf(rid)
            if pdf_path is None:
                raise FileNotFoundError("원문 PDF가 저장소에 없습니다 — 다시 올려주세요")
            parsed = _parse_or_ocr(rid, pdf_path)
            store.write(rid, "parsed", {"pages": parsed.pages, "sections": parsed.sections, "ocr": parsed.ocr})

            store.set_status(rid, "extracting", "사고 정보 구조화 중 (LLM)")
            record = verify_evidence(extract_record(parsed), parsed.pages)  # BE-1: 근거를 원문과 대조
            store.write(rid, "record", record.model_dump())

            store.set_status(rid, "indexing", "유사사고 검색용 색인 중")
            search.index_report(rid)

        store.set_status(rid, "scenario", "판단 훈련 시나리오 생성 중 (LLM)")
        scenario = verify_evidence(build_scenario(parsed, record), parsed.pages)
        store.write(rid, "scenario", scenario.model_dump())
        how = "OCR로 읽음 · " if parsed.ocr else ""
        store.set_status(rid, "done", f"{how}섹션 {len(parsed.sections)}개 인식, 시나리오 {len(scenario.steps)}단계")
    except NeedsOCR as e:
        store.set_status(rid, "ocr_needed", f"OCR이 필요한 PDF입니다 — {e}")
    except Exception as e:  # 해커톤용: 오류를 화면에 그대로 보여준다
        traceback.print_exc()
        store.set_status(rid, "error", f"{type(e).__name__}: {e}")


def _parse_or_ocr(rid: str, pdf_path) -> ParsedReport:
    """레이아웃 파서로 읽고, 글자를 읽을 수 없는 PDF(NeedsOCR)면 OCR로 읽는다 (OCR을 쓸 수 없으면 NeedsOCR 그대로)."""
    from . import ocr

    try:
        return parse_report(pdf_path)
    except NeedsOCR as e:
        if not ocr.enabled():
            raise
        store.set_status(rid, "parsing", f"글자를 읽을 수 없는 PDF — OCR로 읽는 중 ({e})")
        pages = ocr.ocr_pdf(pdf_path, progress=lambda d, n: store.set_status(rid, "parsing", f"OCR로 글자 읽는 중 ({d}/{n}쪽)"))
    hangul = sum(len(re.findall(r"[가-힣]", p)) for p in pages) / max(1, len(pages))
    if hangul < MIN_HANGUL_PER_PAGE:
        raise NeedsOCR(f"OCR로도 글자를 거의 읽지 못했습니다 (쪽당 한글 {hangul:.0f}자)")
    return ParsedReport(pages=pages, sections=split_sections(pages), ocr=True)


def reprocessable(st: dict) -> bool:
    """이 상태의 보고서를 같은 파일로 다시 올렸을 때 다시 처리할지. 'OCR 필요'였는데 이제 OCR을 쓸 수 있으면 다시 처리."""
    from . import ocr

    state = st.get("state")
    if st.get("uploading") or not state or state == "error":
        return True
    if state == "ocr_needed":
        return ocr.enabled()
    return False


def ingest_bytes(data: bytes, filename: str) -> tuple[str, bool]:
    """PDF를 저장소에 넣는다. (id, 새로 처리해야 하는지). 같은 파일이 이미 처리됐으면 건너뛴다."""
    rid = store.report_id(data)
    st = store.read(rid, "status") or {}
    if not reprocessable(st):
        return rid, False
    store.save_pdf(rid, data)
    store.set_status(rid, "queued", "대기 중", filename=filename)
    return rid, True


BUSY = {"queued", "parsing", "extracting", "indexing", "scenario"}


def mark_interrupted() -> None:
    """서버가 처리 도중 꺼졌으면 '처리 중'에 멈춰 있는 건을 다시 올릴 수 있게 오류로 바꾼다.
    서버리스에서는 하지 않는다 (다른 함수 인스턴스가 지금 처리 중일 수 있다 — 대신 heal())."""
    if in_request():
        return
    for rid, docs in store.iter_docs("status"):
        if (docs["status"] or {}).get("state") in BUSY:
            store.set_status(rid, "error", "서버 재시작으로 처리가 중단됨 — 다시 올려주세요")


def in_request() -> bool:
    """서버리스: 처리를 요청 안에서 끝낸다 (백그라운드 작업이 응답 뒤에 살아남지 않음)."""
    return os.getenv("PROCESS_IN_REQUEST") == "1"


STALE_SEC = int(os.getenv("STALE_SEC", "330"))  # Vercel 함수 최대 300초 + 여유


def heal(rid: str, st: dict | None) -> dict | None:
    """서버리스에서 '처리 중'(또는 업로드 중)인 채로 STALE_SEC 넘게 바뀌지 않았으면 함수가 죽은 것이므로 오류로 바꾼다."""
    if not st or not in_request() or st.get("state") not in BUSY:
        return st
    try:
        age = (datetime.now() - datetime.fromisoformat(st.get("updated_at") or st.get("ingested_at") or "")).total_seconds()
    except ValueError:
        return st
    if age <= STALE_SEC:
        return st
    msg = ("PDF 업로드가 끝나지 않았습니다 — 다시 올려주세요" if st.get("uploading")
           else "처리 시간이 초과되었습니다 (서버 함수 시간 제한) — 다시 올려주세요")
    store.set_status(rid, "error", msg)
    return store.read(rid, "status")
