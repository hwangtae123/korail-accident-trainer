"""Supabase(PostgreSQL) 연결. DATABASE_URL이 있을 때만 쓴다 (없으면 store.py가 로컬 파일 저장소를 쓴다).

드라이버는 순수 Python인 pg8000이다. 네이티브 DLL이 없어서 Windows 보안 정책(스마트 앱 컨트롤)에도 막히지 않고,
Docker 이미지도 작다.

DATABASE_URL 예 (Supabase 대시보드 > Connect > Session pooler):
  postgresql://postgres.<project-ref>:<비밀번호>@aws-0-<region>.pooler.supabase.com:5432/postgres
  ※ Direct connection(db.<ref>.supabase.co)은 IPv6 전용이라 IPv4만 되는 호스팅에서는 Session pooler를 쓴다.
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


def run(sql: str, **params: Any) -> list[list]:
    """SQL 한 문장 실행 (:이름 자리표시자). 결과 행 목록. 연결이 끊겨 있으면 한 번 다시 시도한다."""
    for attempt in (1, 2):
        try:
            with connection() as conn:
                return conn.run(sql, **params) or []
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
