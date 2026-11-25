"""이미 처리한 보고서에서 그림·사진을 뽑아 저장한다 (새로 올리는 보고서는 처리 중에 자동으로 뽑는다).
LLM을 부르지 않는다. 원문 PDF는 저장소(Supabase Storage 또는 data/)에서 가져온다.

사용: python scripts/extract_figures.py            그림 목록이 아직 없는 처리 완료 보고서만
      python scripts/extract_figures.py --all      전부 다시
      python scripts/extract_figures.py <id> …     지정한 보고서만
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")
from app import store  # noqa: E402
from app.figures import extract_and_save  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
redo = "--all" in sys.argv
print(f"저장소: {store.backend()}")
total = 0
for rid, docs in store.iter_docs("status", "figures", "record"):
    st = docs["status"] or {}
    if args and rid not in args:
        continue
    if not args and (st.get("state") != "done" or (docs["figures"] is not None and not redo)):
        continue
    title = ((docs["record"] or {}).get("title") or st.get("filename", ""))[:40]
    parsed = store.read(rid, "parsed") or {}
    if parsed.get("ocr"):
        store.write(rid, "figures", [])
        print(f"  {rid} OCR 보고서 — 그림 없음 | {title}")
        continue
    pdf = store.local_pdf(rid)
    if pdf is None:
        print(f"  {rid} 원문 PDF 없음 | {title}")
        continue
    t = time.time()
    metas = extract_and_save(rid, pdf)
    total += len(metas)
    print(f"  {rid} 그림 {len(metas)}개 {time.time() - t:.0f}초 | {title}", flush=True)
print(f"합계 그림 {total}개")
