"""Supabase Storage (원문 PDF 보관). REST API를 httpx로 직접 부른다 (SDK 불필요).

필요한 환경변수: SUPABASE_URL (https://<ref>.supabase.co), SUPABASE_SERVICE_ROLE_KEY (서버 전용, 브라우저에 노출 금지)
버킷: STORAGE_BUCKET (기본 reports, schema.sql이 비공개로 만든다)
"""
import os

import httpx

TIMEOUT = 120


def _conf() -> tuple[str, str, str]:
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        raise RuntimeError("DATABASE_URL을 쓰려면 SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY도 필요합니다 (원문 PDF 보관용)")
    return base, key, os.getenv("STORAGE_BUCKET", "reports")


def _headers(key: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {key}", "apikey": key, **extra}


def upload(path: str, data: bytes, content_type: str = "application/pdf") -> None:
    base, key, bucket = _conf()
    r = httpx.post(f"{base}/storage/v1/object/{bucket}/{path}", content=data, timeout=TIMEOUT,
                   headers=_headers(key, **{"Content-Type": content_type, "x-upsert": "true"}))
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase Storage 업로드 실패 ({r.status_code}): {r.text[:300]}")


def download(path: str) -> bytes | None:
    """없으면 None."""
    base, key, bucket = _conf()
    r = httpx.get(f"{base}/storage/v1/object/{bucket}/{path}", headers=_headers(key), timeout=TIMEOUT)
    if r.status_code in (400, 404):
        return None
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase Storage 다운로드 실패 ({r.status_code}): {r.text[:300]}")
    return r.content
