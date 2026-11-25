"""간단한 비밀번호 잠금. LLM·OCR API 키를 쓰므로 아무나 부르지 못하게 막는다.

ACCESS_PASSWORD가 있으면 /api/* 는 로그인 쿠키가 있어야 한다 (없으면 401).
비어 있으면 잠금 없음 (로컬 개발, 테스트).
로그인 API(/api/login, /api/session)는 계약(openapi.json)에 넣지 않는다 — 화면이 fetch로 직접 부른다.
"""
import hashlib
import hmac
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

COOKIE = "at_session"
MAX_AGE = 30 * 24 * 3600  # 30일
OPEN_PATHS = {"/api/health", "/api/login", "/api/logout", "/api/session"}

router = APIRouter(include_in_schema=False)


def _password() -> str:
    return os.getenv("ACCESS_PASSWORD", "")


def _token(password: str) -> str:
    """쿠키 값: 비밀번호를 그대로 넣지 않고 HMAC으로. 비밀번호를 바꾸면 기존 로그인은 모두 풀린다."""
    return hmac.new(password.encode(), b"accident-trainer-session", hashlib.sha256).hexdigest()


def is_authed(request: Request) -> bool:
    pw = _password()
    if not pw:
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), _token(pw))


async def guard(request: Request, call_next):
    """HTTP 미들웨어: 잠금이 켜져 있으면 로그인 안 한 /api 요청을 401로 돌려준다."""
    path = request.url.path
    if (_password() and path.startswith("/api/") and path not in OPEN_PATHS
            and request.method != "OPTIONS" and not is_authed(request)):
        return JSONResponse(status_code=401, content={"detail": "로그인이 필요합니다"})
    return await call_next(request)


class LoginBody(BaseModel):
    password: str


@router.get("/api/session")
def session(request: Request):
    return {"required": bool(_password()), "ok": is_authed(request)}


@router.post("/api/login")
def login(body: LoginBody, request: Request):
    pw = _password()
    if pw and not hmac.compare_digest(body.password.encode(), pw.encode()):
        return JSONResponse(status_code=401, content={"detail": "비밀번호가 맞지 않습니다"})
    resp = JSONResponse({"ok": True})
    if pw:
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(COOKIE, _token(pw), max_age=MAX_AGE, httponly=True, secure=https, samesite="lax", path="/")
    return resp


@router.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp
