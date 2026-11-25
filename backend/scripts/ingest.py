"""폴더 안의 보고서 PDF를 한꺼번에 처리한다 (서버 없이).
사용: python scripts/ingest.py <PDF 폴더>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from app import store  # noqa: E402
from app.pipeline import ingest_bytes, process  # noqa: E402

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "pdfs")
for pdf in sorted(folder.glob("*.pdf")):
    if "중간" in pdf.name:  # 중간보고서는 최종본과 겹치므로 기본으로 제외
        print(f"건너뜀 (중간보고서): {pdf.name}")
        continue
    rid, is_new = ingest_bytes(pdf.read_bytes(), pdf.name)
    if not is_new:
        print(f"건너뜀 (이미 처리): {pdf.name}")
        continue
    print(f"처리 중: {pdf.name}")
    process(rid)
    print("  ->", store.read(rid, "status"))
