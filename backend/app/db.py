"""Supabase(PostgreSQL) 연결. DATABASE_URL이 있을 때만 쓴다 (없으면 store.py가 로컬 파일 저장소를 쓴다).

드라이버는 순수 Python인 pg8000이다. 네이티브 DLL이 없어서 Windows 보안 정책(스마트 앱 컨트롤)에도 막히지 않고,
Docker 이미지도 작다.

DATABASE_URL 예 (Supabase 대시보드 > Connect > Session pooler):
  postgresql://postgres.<project-ref>:<비밀번호>@aws-0-<region>.pooler.supabase.com:5432/postgres
  ※ Direct connection(db.<ref>.supabase.co)은 IPv6 전용이라 IPv4만 되는 호스팅에서는 Session pooler를 쓴다.
  ※ 서버리스(Vercel)에서는 Transaction pooler(포트 6543)를 쓴다. Session pooler는 동시 연결 15개 제한에 금방 걸린다.
SSL: 기본은 암호화만 하고 인증서는 검증하지 않는다 (libpq sslmode=require와 같음).
     DATABASE_SSL_ROOT_CERT=<Supabase CA 인증서 경로>를 주면 인증서까지 검증한다.
"""
import json
import os
import queue
import ssl
import threading
from contextlib import contextmanager
from typing import Any
from urllib.parse import unquote, urlparse

POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
_pool: "queue.LifoQueue | None" = None
_created = 0
_lock = threading.Lock()


def url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def enabled() -> bool:
    return bool(url())


def _ssl_context() -> ssl.SSLContext | None:
    u = urlparse(url())
    mode = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p).get("sslmode", "require")
    if mode == "disable" or u.hostname in ("localhost", "127.0.0.1"):
        return None
    root = os.getenv("DATABASE_SSL_ROOT_CERT")
    if root:
        return ssl.create_default_context(cafile=root)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _connect():
    import pg8000.native

    u = urlparse(url())
    if u.scheme not in ("postgres", "postgresql"):
        raise RuntimeError("DATABASE_URL은 postgresql://… 형식이어야 합니다")
    return pg8000.native.Connection(
        user=unquote(u.username or "postgres"), password=unquote(u.password or ""),
        host=u.hostname or "localhost", port=u.port or 5432, database=(u.path or "/postgres").lstrip("/") or "postgres",
        ssl_context=_ssl_context(), timeout=30, application_name="accident-trainer",
    )


@contextmanager
def connection():
    """풀에서 연결 하나를 빌린다. 연결이 끊겼으면 버리고 새로 만든다."""
    global _pool, _created
    with _lock:
        if _pool is None:
            _pool = queue.LifoQueue()
        try:
            conn = _pool.get_nowait()
        except queue.Empty:
            conn = None
            if _created < POOL_SIZE:
                _created += 1
                make = True
            else:
                make = False
    if conn is None:
        if make:
            try:
                conn = _connect()
            except Exception:
                with _lock:
                    _created -= 1
                raise
        else:
            conn = _pool.get(timeout=60)
    ok = False
    try:
        yield conn
        ok = True
    finally:
        if ok:
            _pool.put(conn)
        else:  # 오류가 난 연결은 상태를 알 수 없으므로 닫고 버린다
            try:
                conn.close()
            except Exception:
                pass
            with _lock:
                _created -= 1


def _pin_tx() -> bool:
    """Supabase Transaction pooler(포트 6543)인가. 이때는 쿼리마다 트랜잭션으로 감싸야 한다:
    pg8000은 한 쿼리를 '준비(Parse)'와 '실행(Bind)' 두 번에 나눠 보내는데, 트랜잭션 밖이면 풀러가 둘을
    서로 다른 DB 연결로 보낼 수 있어 동시 요청이 많을 때 'unnamed prepared statement does not exist',
    'bind message supplies N parameters' 오류가 난다. 트랜잭션 안에서는 한 연결에 묶인다."""
    if os.getenv("DB_PIN_TX") in ("0", "1"):
        return os.getenv("DB_PIN_TX") == "1"
    return urlparse(url()).port == 6543


def _run_once(conn, sql: str, params: dict) -> list[list]:
    if not _pin_tx():
        return conn.run(sql, **params) or []
    conn.execute_simple("begin")  # 단순 쿼리(메시지 하나)라 풀러가 나누지 않는다
    try:
        rows = conn.run(sql, **params) or []
        conn.execute_simple("commit")
        return rows
    except Exception:
        try:
            conn.execute_simple("rollback")
        except Exception:
            pass
        raise


def run(sql: str, **params: Any) -> list[list]:
    """SQL 한 문장 실행 (:이름 자리표시자). 결과 행 목록. 연결이 끊겨 있으면 한 번 다시 시도한다."""
    for attempt in (1, 2):
        try:
            with connection() as conn:
                return _run_once(conn, sql, params)
        except Exception as e:  # noqa: PERF203
            name = type(e).__name__
            if attempt == 1 and name in ("InterfaceError", "BrokenPipeError", "ConnectionResetError", "OSError"):
                continue
            raise
    return []


def run_script(sql: str) -> None:
    """여러 문장 SQL (schema.sql 적용용)."""
    with connection() as conn:
        for stmt in _split(sql):
            conn.run(stmt)


def _split(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def jsonb(obj) -> str | None:
    return None if obj is None else json.dumps(obj, ensure_ascii=False)


def reset_pool() -> None:
    global _pool, _created
    with _lock:
        if _pool is not None:
            while not _pool.empty():
                try:
                    _pool.get_nowait().close()
                except Exception:
                    pass
        _pool, _created = None, 0
