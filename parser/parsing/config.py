"""설정 읽기. 처리할 문서는 환경 변수 PARSE_DOC (doc_id)로 고른다 (safeio.DOC_ID).

  config/docs/<doc_id>.yaml      문서 설정: PDF, 프로필 이름, 이 문서만의 임계값 (params), 구역 (zones), 평가용 쪽 (eval)
  config/profiles/<이름>.yaml     양식 프로필: 폰트 역할, 박스 라벨, 양식 코드, 참조 규칙 (같은 양식 문서끼리 같이 씀)
  config/params.yaml             공통 임계값. 프로필의 params, 그 위에 문서 설정의 params가 덮어쓴다
data/의 PDF와 문서 설정 짝짓기, 새 PDF의 문서 설정·프로필 초안 만들기는 parsing/docs.py, parsing/profile_draft.py.

check_profile(): 덤프한 글자의 폰트 분포로 프로필 폰트가 실제로 쓰였는지, 가장 많이 쓰인 폰트가 body와 같은지 확인한다.
"""

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from safeio import DOC_ID, DOCS_DIR, ROOT

CONFIG_DIR = ROOT / "config"
PROFILES_DIR = CONFIG_DIR / "profiles"
UNSET = "UNSET/0"  # 이 문서에 없는 폰트 역할 (어느 줄과도 맞지 않음)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def doc_id() -> str:
    return DOC_ID


@lru_cache(maxsize=None)
def doc() -> dict:
    return _load(DOCS_DIR / f"{doc_id()}.yaml")


def profile_name() -> str:
    return doc().get("profile") or "default"


@lru_cache(maxsize=None)
def profile() -> dict:
    return _load(PROFILES_DIR / f"{profile_name()}.yaml")


@lru_cache(maxsize=None)
def params() -> dict:
    return _merge(_merge(_load(CONFIG_DIR / "params.yaml"), profile().get("params") or {}), doc().get("params") or {})


def P(key: str) -> Any:
    """점으로 이은 이름으로 파라미터 값을 읽는다. 예: P("tables.row_tol_pt"). 문서 설정의 params가 우선."""
    node: Any = params()
    for part in key.split("."):
        node = node[part]
    return node


def doc_pdf() -> Path:
    return ROOT / doc()["pdf"]


def final_zones() -> list[tuple[int, int, str, bool]]:
    return [(int(a), int(b), str(z), bool(inc)) for a, b, z, inc in doc()["zones"]]


def mode() -> str:
    """문서 구조 모드: articles (조문형 약관: 편·관·조, 기본) / report (장·절 번호 보고서)."""
    return profile().get("mode") or "articles"


def font(role: str) -> Any:
    """프로필의 폰트 역할 값 (문자열 또는 목록). body: auto면 문서 설정의 body_font (새 문서를 만들 때 채움)."""
    v = profile()["fonts"][role]
    if v == "auto":
        return doc().get("body_font") or UNSET
    return v


def fonts_of(role: str) -> list[str]:
    v = font(role)
    return list(v) if isinstance(v, list) else [v]


def base_font(name: str) -> str:
    return name.split("+", 1)[-1]


def is_bold_font(name: str) -> bool:
    b = base_font(name)
    return any(b.startswith(pref) for pref in profile()["bold_font_prefixes"]) or "Bold" in b


@lru_cache(maxsize=None)
def form_code_re() -> re.Pattern:
    return re.compile(profile()["form_code_regex"])


@lru_cache(maxsize=None)
def _caption_res() -> tuple:
    return tuple(re.compile(x) for x in profile().get("caption_patterns") or [])


def caption_kind(text: str) -> tuple[str, str] | None:
    """그림·표 설명 줄이면 (figure|table, 번호 글자), 아니면 None. 프로필 caption_patterns가 없으면 늘 None.
    줄 전체가 60자 이하이고 문장 끝 ("다.")이 아닐 때만."""
    t = text.strip()
    if not t or len(t) > 60 or t.endswith(("다.", "다")):
        return None
    for rx in _caption_res():
        m = rx.match(t)
        if m:
            kind = "table" if re.search(r"표", m.group(0)) and not re.search(r"(그림|사진)", m.group(0)) else "figure"
            num = re.search(r"\d+(?:[-.]\d+)*", m.group(0))
            return kind, (num.group(0) if num else "")
    return None


def box_labels() -> dict[str, str]:
    return dict(profile()["box_labels"])


def box_kinds_not_table() -> tuple[str, ...]:
    return tuple(profile()["box_kinds_not_table"])


def check_profile(font_char_counts: Counter) -> list[str]:
    """프로필 폰트 확인. 반환: 경고 코드 목록 (원문 없음, 폰트 키만)."""
    warns = []
    used = {k for k, n in font_char_counts.items() if n > 0}
    for role in profile()["fonts"]:
        value = font(role)
        for fk in (value if isinstance(value, list) else [value]):
            if fk != UNSET and fk not in used:
                warns.append(f"profile_font_unused:{role}:{fk}")
    if font_char_counts:
        top = font_char_counts.most_common(1)[0][0]
        if top != font("body"):
            warns.append(f"body_font_mismatch:profile={font('body')}:most_common={top}")
    return warns
