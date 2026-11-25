"""모든 테스트 공통: .env에 Supabase·LLM 키가 있어도 테스트는 로컬 파일 저장소와 가짜 LLM·임베딩만 쓴다.
(load_dotenv는 이미 있는 환경변수를 덮어쓰지 않으므로 여기서 먼저 비워 둔다.)
Supabase 연동 시험은 tests/test_supabase.py (TEST_DATABASE_URL이 있을 때만 돈다).
"""
import os

os.environ["DATABASE_URL"] = ""
os.environ["VECTOR_STORE"] = "simple"
os.environ.setdefault("LLM_PROVIDER", "stub")
os.environ.setdefault("EMBED_PROVIDER", "stub")
