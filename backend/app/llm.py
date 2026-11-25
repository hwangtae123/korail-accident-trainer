"""LLM 호출을 한곳에 모은다. 공급자는 환경변수로 바꾼다.

LLM_PROVIDER=anthropic  (기본)  ANTHROPIC_API_KEY 필요
LLM_PROVIDER=openai             OPENAI_API_KEY 필요. OPENAI_BASE_URL을 주면
                                OpenAI 호환 서버(vLLM, Ollama 등 사내 GPU)도 그대로 쓸 수 있다.
LLM_PROVIDER=stub               키 없이 흐름만 확인 (tests/에서 사용)
"""
import json
import os
import re
from typing import Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# 테스트에서 끼워 넣는 가짜 LLM: (system, user) -> 응답 문자열
_stub: Callable[[str, str], str] | None = None


def set_stub(fn: Callable[[str, str], str] | None) -> None:
    global _stub
    _stub = fn


def _complete(system: str, user: str) -> str:
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "stub" or _stub is not None:
        if _stub is None:
            raise RuntimeError("LLM_PROVIDER=stub 인데 set_stub()이 호출되지 않았습니다")
        return _stub(system, user)

    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=os.getenv("LLM_MODEL", "claude-sonnet-5-5"),
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    if provider == "openai":
        from openai import OpenAI

        model = os.getenv("LLM_MODEL")
        if not model:
            raise RuntimeError("LLM_PROVIDER=openai 일 때는 LLM_MODEL을 지정하세요")
        client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    raise RuntimeError(f"알 수 없는 LLM_PROVIDER: {provider}")


def _extract_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def complete_text(system: str, user: str) -> str:
    return _complete(system, user)


def complete_json(system: str, user: str, model_cls: Type[T], retries: int = 1) -> T:
    """JSON으로 답하게 하고 Pydantic으로 검증한다. 실패하면 오류를 알려주고 한 번 더 묻는다."""
    schema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    sys_prompt = (
        f"{system}\n\n반드시 아래 JSON Schema를 따르는 JSON 객체 하나만 출력하세요. "
        f"설명 문장은 쓰지 마세요.\n{schema}"
    )
    prompt = user
    last_err = None
    for _ in range(retries + 1):
        text = _complete(sys_prompt, prompt)
        try:
            return model_cls.model_validate(_extract_json(text))
        except (ValueError, ValidationError) as e:
            last_err = e
            prompt = f"{user}\n\n[이전 출력이 형식 검증에 실패했습니다: {str(e)[:800]}]\n형식을 고쳐서 다시 출력하세요."
    raise RuntimeError(f"LLM 출력 검증 실패: {last_err}")
