"""규정·지침 이름 맞추기 (backlog BE-4).

LLM이 뽑은 규정 이름은 보고서마다 표기가 다르다:
  "선로유지관리지침" / "선로 유지관리 지침" / "「선로유지관리지침」" / "한국철도공사 선로유지관리지침" / "선로유지관리지침 제12조"
canonical_key()는 이것들을 같은 키로 바꾼다. 비교(shared_rules)와 집계(/api/stats)에 쓴다.

규칙 (순서대로)
1. 괄호·따옴표·가운뎃점·공백을 뺀다
2. 끝에 붙은 조·항·호 ("제12조", "제40조의2제1항", "별표3")를 뗀다
3. 앞에 붙은 기관 이름 ("한국철도공사", "코레일", "(사)…")을 뗀다
4. ALIASES 사전으로 약칭·옛 이름을 대표 이름으로 바꾼다

ALIASES는 실제 보고서를 넣어 보면서 채운다. 키·값 모두 1~3을 거친 형태(공백 없이)로 적는다.
"""
import re

# 약칭·다른 이름 -> 대표 이름 (공백 없이). 실제 보고서에서 확인한 표기만 넣는다.
ALIASES: dict[str, str] = {
    "차량운전규칙": "철도차량운전규칙",
}

ORG_PREFIXES = ("한국철도공사", "코레일", "KORAIL", "국가철도공단", "한국철도시설공단", "서울교통공사",
                "부산교통공사", "공항철도", "(주)", "(사)")

_STRIP = re.compile(r"[\s「」『』()（）\[\]<>《》〈〉\"'“”‘’·ㆍ,]")
_ARTICLE = re.compile(r"(제\d+(조|항|호|관|장|절)(의\d+)?)+.*$|별표\d*.*$|부칙.*$")


def canonical_key(name: str) -> str:
    raw = name or ""
    for p in ORG_PREFIXES:  # 괄호를 지우기 전에 "(주)" 같은 접두어부터
        if raw.strip().startswith(p) and len(raw.strip()) > len(p):
            raw = raw.strip()[len(p):]
            break
    key = _STRIP.sub("", raw)
    key = _ARTICLE.sub("", key) or _STRIP.sub("", raw)  # 조항만 있는 이름이면 그대로 둔다
    for p in ORG_PREFIXES:
        p = _STRIP.sub("", p)
        if key.startswith(p) and len(key) > len(p):
            key = key[len(p):]
            break
    return ALIASES.get(key, key)
