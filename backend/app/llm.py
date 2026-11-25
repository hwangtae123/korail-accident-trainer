"""LLM 호출을 한곳에 모은다. 기본 공급자가 죽으면 대체 공급자로 넘어간다 (임베딩은 app/search.py, 대체 없음).

기본:  LLM_PROVIDER=openai (OPENAI_API_KEY, LLM_MODEL) | anthropic (ANTHROPIC_API_KEY) | stub (테스트)
대체:  LLM_FALLBACK_PROVIDER=gemini (기본: GEMINI_API_KEY가 있으면 gemini, 없으면 대체 없음, none이면 끔)
       LLM_FALLBACK_MODEL (기본 gemini-3.6-flash, 무료 등급. 3.8-flash는 무료 등급에서 응답 없음·503이 잦았음)
       Gemini는 OpenAI 호환 주소(generativelanguage.googleapis.com/v1beta/openai/)로 부르므로 SDK를 더 깔지 않는다.

언제 넘어가나: 기본 공급자 호출이 실패(장애·시간 초과·속도 제한·키 오류)하거나, JSON 형식 검증에 연달아 실패할 때.
LLM_TIMEOUT(초, 기본 90)과 재시도 1회로 묶어서, 기본이 죽어도 Vercel 함수 시간(300초) 안에 대체로 넘어간다.
OPENAI_BASE_URL을 주면 OpenAI 호환 서버(vLLM, Ollama 등 사내 GPU)를 기본으로 쓸 수 있다.
"""
import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"

# 테스트에서 끼워 넣는 가짜 LLM: (system, user) -> 응답 문자열
_stub: Callable[[str, str], str] | None = None
# 마지막으로 답한 공급자 (스레드별) — 처리 상태 메시지에 "Gemini로 대체" 표시용
_last = threading.local()


def set_stub(fn: Callable[[str, str], str] | None) -> None:
    global _stub
    _stub = fn


class LLMError(RuntimeError):
    """LLM 호출 실패 (키 없음, 네트워크, 모델 이름 오류, 출력 형식 오류 등). API는 502 + 이유로 돌려준다."""


@dataclass
class Provider:
    name: str   # openai | anthropic | gemini
    model: str

    @property
    def label(self) -> str:
        return {"openai": "GPT", "anthropic": "Claude", "gemini": "Gemini"}.get(self.name, self.name)


def _timeout() -> float:
    return float(os.getenv("LLM_TIMEOUT", "90"))


def providers() -> list[Provider]:
    """기본 + 대체 공급자 목록 (순서대로 시도)."""
    primary = os.getenv("LLM_PROVIDER", "anthropic").lower()
    default_model = {"anthropic": "claude-sonnet-5-5"}.get(primary, "")
    chain = [Provider(primary, os.getenv("LLM_MODEL") or default_model)]
    fb = (os.getenv("LLM_FALLBACK_PROVIDER") or ("gemini" if os.getenv("GEMINI_API_KEY") else "none")).lower()
    if fb not in ("", "none", primary):
        model = os.getenv("LLM_FALLBACK_MODEL") or (DEFAULT_GEMINI_MODEL if fb == "gemini" else "")
        chain.append(Provider(fb, model))
    return chain


def openai_client(p: Provider):
    """OpenAI SDK 클라이언트 (Gemini도 OpenAI 호환 주소로). OCR도 이걸 쓴다."""
    from openai import OpenAI

    if p.name == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY가 없습니다")
        return OpenAI(api_key=key, base_url=os.getenv("GEMINI_BASE_URL") or GEMINI_BASE_URL,
                      timeout=_timeout(), max_retries=1)
    return OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=_timeout(), max_retries=1)


def _call(p: Provider, system: str, user: str) -> str:
    if p.name == "anthropic":
        import anthropic

        client = anthropic.Anthropic(timeout=_timeout(), max_retries=1)
        resp = client.messages.create(model=p.model, max_tokens=8000, system=system,
                                      messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if b.type == "text")
    if p.name in ("openai", "gemini"):
        if not p.model:
            raise LLMError(f"{p.name}: 모델 이름이 없습니다 (LLM_MODEL / LLM_FALLBACK_MODEL)")
        resp = openai_client(p).chat.completions.create(
            model=p.model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return resp.choices[0].message.content or ""
    raise LLMError(f"알 수 없는 LLM 공급자: {p.name}")


def _describe(e: Exception) -> str:
    msg = f"{type(e).__name__}: {str(e)[:300]}"
    if any(k in msg.lower() for k in ("api_key", "authentication", "auth", "401")):
        msg += " — .env의 API 키를 확인하세요"
    return msg


def reset_fallback() -> None:
    """이 스레드의 '대체 공급자를 썼는지' 기록을 지운다 (보고서 처리 시작 때)."""
    _last.fallback = ""


def fallback_used() -> str:
    """reset_fallback() 이후 대체 공급자가 답한 적이 있으면 그 이름 (예: 'Gemini'), 없으면 ''."""
    return getattr(_last, "fallback", "")


def last_provider() -> str:
    """이 스레드에서 마지막으로 답한 공급자 이름 (예: 'Gemini'). 없으면 ''."""
    return getattr(_last, "label", "")


def _run(fn: Callable[[Provider], str]) -> str:
    """공급자를 차례로 시도한다. fn이 성공하면 그 결과, 모두 실패하면 LLMError (각 공급자의 이유 포함)."""
    if _stub is not None or os.getenv("LLM_PROVIDER", "anthropic").lower() == "stub":
        if _stub is None:
            raise RuntimeError("LLM_PROVIDER=stub 인데 set_stub()이 호출되지 않았습니다")
        _last.label = "stub"
        return fn(Provider("stub", "stub"))  # 테스트용 가짜 LLM의 예외는 그대로 둔다
    errors = []
    for i, p in enumerate(providers()):
        try:
            out = fn(p)
            _last.label = p.label
            if i > 0:
                _last.fallback = p.label
                print(f"[llm] {errors[-1]} → {p.label}({p.model})로 대체", file=sys.stderr, flush=True)
            return out
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p.label} 실패 ({_describe(e)})")
    raise LLMError(" / ".join(errors))


def _call_any(p: Provider, system: str, user: str) -> str:
    return _stub(system, user) if p.name == "stub" else _call(p, system, user)


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def complete_text(system: str, user: str) -> str:
    return _run(lambda p: _call_any(p, system, user))


def complete_json(system: str, user: str, model_cls: Type[T], retries: int = 1) -> T:
    """JSON으로 답하게 하고 Pydantic으로 검증한다. 형식이 틀리면 이유를 알려주고 한 번 더 묻고,
    그래도 틀리면 대체 공급자로 넘어간다."""
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    sys_prompt = (
        f"{system}\n\n반드시 아래 JSON Schema를 따르는 JSON 객체 하나만 출력하세요. "
        f"설명 문장은 쓰지 마세요.\n{schema}"
    )
    result: dict = {}

    def attempt(p: Provider) -> str:
        prompt, last_err = user, None
        for _ in range(retries + 1):
            text = _call_any(p, sys_prompt, prompt)
            try:
                result["value"] = model_cls.model_validate(_extract_json(text))
                return text
            except (ValueError, ValidationError) as e:
                last_err = e
                prompt = f"{user}\n\n[이전 출력이 형식 검증에 실패했습니다: {str(e)[:800]}]\n형식을 고쳐서 다시 출력하세요."
        raise LLMError(f"출력 형식 검증 실패: {last_err}")

    try:
        _run(attempt)
    except LLMError:
        raise
    except Exception as e:  # stub 모드에서 검증 실패 등
        raise LLMError(str(e)) from e
    return result["value"]
