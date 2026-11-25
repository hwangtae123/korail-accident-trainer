"""프론트 개발용 가짜 데이터 2건을 data/에 만든다 (API 키 없이).
내용은 테스트용으로 지어낸 것이며 실제 사고가 아니다. 제목에 '테스트용 가상 보고서'가 붙는다.
사용: python scripts/seed_dev.py   (backend/ 에서) -> 이후 uvicorn을 EMBED_PROVIDER=stub로 실행
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("EMBED_PROVIDER", "stub")

from app import llm, store  # noqa: E402
from app.pipeline import ingest_bytes, process  # noqa: E402
from tests.test_flow import fake_llm, make_pdf  # noqa: E402

llm.set_stub(fake_llm)
for tag in ["A", "B"]:
    pdf = Path(tempfile.mkdtemp()) / f"{tag}.pdf"
    make_pdf(pdf, tag)
    rid, is_new = ingest_bytes(pdf.read_bytes(), f"테스트용_가상_보고서_{tag}.pdf")
    if is_new:
        process(rid)
    print(tag, rid, store.read(rid, "status")["state"])
print(f"데이터 위치: {store.DATA_DIR}")
print("서버 실행: EMBED_PROVIDER=stub uvicorn app.main:app --reload --port 8000")
