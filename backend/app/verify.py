"""근거 자동 확인 (backlog BE-1).

LLM이 붙인 Evidence(page, quote)를 파싱 텍스트와 대조해서 verified를 채운다.
- quote가 그 쪽 원문에 있으면 True, 없으면 False, quote나 page가 비어 있으면 None
- 공백·줄바꿈 차이는 무시한다 (PDF 줄바꿈, 글자 간격 때문에 띄어쓰기가 원문과 다를 수 있다)
- LLM이 줄임표(… / ...)로 중간을 생략했으면, 나뉜 조각이 그 쪽에 순서대로 모두 있을 때 True
- LLM이 verified를 채워 보내도 무시하고 이 결과로 덮어쓴다
"""
import re
from typing import Any

from pydantic import BaseModel

from .schema import Evidence

_PAGE_MARK = re.compile(r"^\[p\.(\d+)\]")
_WS = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"…+|\.{3,}|⋯+")
_EDGE_QUOTES = "\"'“”‘’「」『』"


def _norm(text: str) -> str:
    return _WS.sub("", text)


def page_texts(pages: list[str]) -> dict[int, str]:
    """["[p.1]\\n본문", ...] -> {1: "공백을 뺀 본문"}. 쪽 표시가 없으면 순서(1부터)를 쪽 번호로 쓴다."""
    out: dict[int, str] = {}
    for i, text in enumerate(pages, start=1):
        m = _PAGE_MARK.match(text)
        n = int(m.group(1)) if m else i
        body = text[m.end():] if m else text
        out[n] = out.get(n, "") + _norm(body)
    return out


def check(ev: Evidence, pages: dict[int, str]) -> bool | None:
    quote = (ev.quote or "").strip().strip(_EDGE_QUOTES)
    if not quote or ev.page is None:
        return None
    text = pages.get(ev.page)
    if text is None:
        return False
    parts = [_norm(p) for p in _ELLIPSIS.split(quote)]
    parts = [p for p in parts if p]
    if not parts:
        return None
    pos = 0
    for p in parts:
        idx = text.find(p, pos)
        if idx < 0:
            return False
        pos = idx + len(p)
    return True


def _walk(obj: Any, pages: dict[int, str]) -> None:
    if isinstance(obj, Evidence):
        obj.verified = check(obj, pages)
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            _walk(getattr(obj, name), pages)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _walk(x, pages)


def verify_evidence(model: BaseModel, pages: list[str]) -> BaseModel:
    """model 안의 모든 Evidence의 verified를 제자리에서 채우고 model을 돌려준다."""
    _walk(model, page_texts(pages))
    return model
