"""PDF 한 건을 끝까지 처리한다: 파싱 -> 구조화 -> 시나리오. 단계마다 결과를 저장한다."""
import traceback

from . import search, store
from .extract import build_scenario, extract_record
from .parse import NeedsOCR, ParsedReport, parse_report
from .schema import AccidentRecord


def process(rid: str, only_scenario: bool = False) -> None:
    try:
        pdf_path = store.rdir(rid) / "report.pdf"
        if only_scenario:
            parsed = ParsedReport(**store.read(rid, "parsed"))
            record = AccidentRecord(**store.read(rid, "record"))
        else:
            store.set_status(rid, "parsing", "PDF 텍스트 추출 중")
            parsed = parse_report(pdf_path)
            store.write(rid, "parsed", {"pages": parsed.pages, "sections": parsed.sections})

            store.set_status(rid, "extracting", "사고 정보 구조화 중 (LLM)")
            record = extract_record(parsed)
            store.write(rid, "record", record.model_dump())

            store.set_status(rid, "indexing", "유사사고 검색용 색인 중 (ChromaDB)")
            search.index_report(rid)

        store.set_status(rid, "scenario", "판단 훈련 시나리오 생성 중 (LLM)")
        scenario = build_scenario(parsed, record)
        store.write(rid, "scenario", scenario.model_dump())
        store.set_status(rid, "done", f"섹션 {len(parsed.sections)}개 인식, 시나리오 {len(scenario.steps)}단계")
    except NeedsOCR as e:
        store.set_status(rid, "ocr_needed", f"OCR이 필요한 PDF입니다 — {e}")
    except Exception as e:  # 해커톤용: 오류를 화면에 그대로 보여준다
        traceback.print_exc()
        store.set_status(rid, "error", f"{type(e).__name__}: {e}")


def ingest_bytes(data: bytes, filename: str) -> tuple[str, bool]:
    """PDF를 저장소에 넣는다. (id, 새로 처리해야 하는지). 같은 파일이 이미 처리됐으면 건너뛴다."""
    rid = store.report_id(data)
    st = store.read(rid, "status") or {}
    if st.get("state") in {"done", "ocr_needed"} | BUSY:
        return rid, False
    (store.rdir(rid) / "report.pdf").write_bytes(data)
    store.set_status(rid, "queued", "대기 중", filename=filename)
    return rid, True


BUSY = {"queued", "parsing", "extracting", "indexing", "scenario"}


def mark_interrupted() -> None:
    """서버가 처리 도중 꺼졌으면 '처리 중'에 멈춰 있는 건을 다시 올릴 수 있게 오류로 바꾼다."""
    for rid in store.list_ids():
        if (store.read(rid, "status") or {}).get("state") in BUSY:
            store.set_status(rid, "error", "서버 재시작으로 처리가 중단됨 — 다시 올려주세요")
