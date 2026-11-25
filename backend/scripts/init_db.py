"""Supabase에 테이블·pgvector·Storage 버킷을 만든다 (supabase/schema.sql). 여러 번 실행해도 된다.
사용: python scripts/init_db.py   (backend/ 에서, .env에 DATABASE_URL)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")
from app import db  # noqa: E402

if not db.enabled():
    sys.exit("DATABASE_URL이 없습니다 (.env 확인)")
db.run_script((ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8"))
n_reports = db.run("select count(*) from public.reports")[0][0]
n_chunks = db.run("select count(*) from public.report_chunks")[0][0]
bucket = db.run("select id, public from storage.buckets where id = 'reports'")
print(f"스키마 적용 완료: reports {n_reports}건, report_chunks {n_chunks}개, 버킷 {bucket}")
