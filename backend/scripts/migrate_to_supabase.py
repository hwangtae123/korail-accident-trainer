"""로컬 파일 저장소(backend/data/)에 처리해 둔 보고서를 Supabase로 옮긴다.
문서 4개(status·parsed·record·scenario) -> public.reports, 원문 PDF -> Storage,
검색 조각 -> public.report_chunks (data/vectors에 있는 임베딩을 그대로 옮겨 임베딩 비용이 들지 않는다).
LLM은 부르지 않는다. 여러 번 실행해도 된다 (덮어씀).

사용: python scripts/migrate_to_supabase.py [로컬 data 폴더]   (backend/ 에서, .env에 DATABASE_URL·SUPABASE_*)
      로컬 임베딩이 없거나 EMBED_MODEL이 다르면 --reindex 를 붙여 Supabase에서 임베딩을 새로 만든다.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")
from app import db, store  # noqa: E402
from app.vectorstore import PgCollection, SimpleCollection  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
reindex = "--reindex" in sys.argv
src = Path(args[0]) if args else ROOT / "data"
if not db.enabled():
    sys.exit("DATABASE_URL이 없습니다 (.env 확인)")

ids = sorted(p.name for p in src.iterdir() if (p / "status.json").exists())
print(f"옮길 보고서 {len(ids)}건 ({src})")
for rid in ids:
    d = src / rid
    status = json.loads((d / "status.json").read_text(encoding="utf-8"))
    # status를 먼저 넣어야 행이 생긴다
    store.write(rid, "status", status)
    for name in ("parsed", "record", "scenario"):
        f = d / f"{name}.json"
        if f.exists():
            store.write(rid, name, json.loads(f.read_text(encoding="utf-8")))
    pdf = d / store.PDF_NAME
    if pdf.exists():
        from app import supa_storage

        supa_storage.upload(f"{rid}/{store.PDF_NAME}", pdf.read_bytes())
    print(f"  {rid} {status.get('state')} {status.get('filename', '')[:50]}")

pg = PgCollection()
if reindex:
    from app import search

    n = {rid: search.index_report(rid) for rid in ids if (src / rid / "record.json").exists()}
    print(f"임베딩 새로 만듦: {n}")
else:
    local = SimpleCollection(src / "vectors")
    if local.count() == 0:
        print("로컬 임베딩이 없습니다 — --reindex 로 다시 실행하세요")
    else:
        for rid in ids:
            idx = [i for i, m in enumerate(local.metadatas) if m["report_id"] == rid]
            if not idx:
                continue
            pg.delete(where={"report_id": rid})
            pg.add([local.ids[i] for i in idx], [local.documents[i] for i in idx],
                   [local.emb[i].tolist() for i in idx], [local.metadatas[i] for i in idx])
        print(f"검색 조각 {local.count()}개 옮김 (차원 {local.emb.shape[1]})")
print(f"Supabase: reports {db.run('select count(*) from public.reports')[0][0]}건, "
      f"report_chunks {pg.count()}개")
