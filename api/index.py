"""Vercel Python 함수 진입점: backend/app/main.py의 FastAPI 앱을 그대로 쓴다 (/api/* 는 vercel.json이 여기로 보낸다).

서버리스 설정:
- PROCESS_IN_REQUEST=1: 보고서 처리를 요청 안에서 끝낸다 (응답 뒤 백그라운드 작업이 보장되지 않음)
- DATA_DIR=/tmp/…: 쓸 수 있는 곳은 /tmp뿐 (PDF 사본, 레이아웃 파서 작업 폴더). 데이터는 Supabase에 있다
- LAYOUT_PARSER_TIMEOUT: 함수 시간 제한(300초) 안에서 파서가 먼저 멈추도록
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("PROCESS_IN_REQUEST", "1")
os.environ.setdefault("DATA_DIR", "/tmp/accident-trainer")
os.environ.setdefault("LAYOUT_PARSER_TIMEOUT", "200")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
# 함수 인스턴스마다 DB 연결을 적게 (여러 인스턴스가 동시에 뜬다). DATABASE_URL은 Supabase Transaction pooler(6543)를 쓴다.
os.environ.setdefault("DB_POOL_SIZE", "2")

from app.main import app  # noqa: E402,F401
