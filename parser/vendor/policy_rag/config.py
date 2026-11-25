"""파싱·청킹·Bedrock·검색·챗봇 설정 (config.yaml의 table, body, chunk, bedrock, ask, chat 섹션).

예외 메시지에는 설정 파일의 값이나 내용을 넣지 않고, 항목 이름과 조건만 적는다.
"""

import math
from dataclasses import dataclass, field, fields
from typing import Any

import yaml

# 0 이상이어야 하는 수치 항목 (pt 단위)
_NON_NEGATIVE_FIELDS = ("snap_tol", "thin_rect_max_width", "min_line_length", "note_max_gap", "dash_max_gap")
_STRING_FIELDS = ("header_join", "cell_line_join")


@dataclass
class TableConfig:
    """표 파싱 설정. 수치 기본값은 초기 제안값"""

    snap_tol: float = 1.5
    line_min_coverage: float = 0.9
    thin_rect_max_width: float = 2.0
    min_line_length: float = 3.0
    header_join: str = "-"
    cell_line_join: str = " "
    note_prefixes: list[str] = field(default_factory=lambda: ["(주)", "※"])
    note_max_gap: float = 10.0
    dash_max_gap: float = 4.0
    dash_min_pieces: int = 3
    images_as_lines: bool = True

    def __post_init__(self) -> None:
        for name in _NON_NEGATIVE_FIELDS + ("line_min_coverage",):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name}: 숫자여야 한다")
            if not math.isfinite(value):
                raise ValueError(f"{name}: 유한한 값이어야 한다")
            setattr(self, name, float(value))
        for name in _NON_NEGATIVE_FIELDS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name}: 0 이상이어야 한다")
        if not 0 < self.line_min_coverage <= 1:
            raise ValueError("line_min_coverage: 0 초과 1 이하여야 한다")
        if isinstance(self.dash_min_pieces, bool) or not isinstance(self.dash_min_pieces, int):
            raise ValueError("dash_min_pieces: 정수여야 한다")
        if self.dash_min_pieces < 2:
            raise ValueError("dash_min_pieces: 2 이상이어야 한다")
        if not isinstance(self.images_as_lines, bool):
            raise ValueError("images_as_lines: true 또는 false여야 한다")
        for name in _STRING_FIELDS:
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name}: 문자열이어야 한다")
        # 주석 줄의 시작 표식 목록. 줄 시작 비교는 NFKC 정규화 후 하므로 호환 문자 ("㈜" 등)도 잡는다
        if (
            not isinstance(self.note_prefixes, list)
            or not self.note_prefixes
            or not all(isinstance(p, str) and p.strip() for p in self.note_prefixes)
        ):
            raise ValueError("note_prefixes: 비어 있지 않은 문자열의 비어 있지 않은 목록이어야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TableConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            # 키 이름도 파일 내용이므로 개수만 알린다
            raise ValueError(f"알 수 없는 table 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


# 본문 번호 체계의 종류 (policy_rag.ingest.body가 종류별 패턴과 순번 계산을 가진다)
# article ("제N조")은 조 체계 문서용이다. 기본 levels에는 넣지 않는다.
BODY_LEVEL_KINDS = ("arabic_dot", "hangul_dot", "paren_arabic", "circled", "article")
DEFAULT_BODY_LEVELS = ("arabic_dot", "hangul_dot", "paren_arabic", "circled")


@dataclass
class BodyConfig:
    """본문 파싱 설정. 회사 공통 스타일만 두고, 문서마다 다른 값(본문 페이지 등)은 두지 않는다.

    levels: 번호 체계. 목록 순서가 곧 단계다 (0 = 가장 바깥).
    line_join: 한 항목 안에서 줄바꿈된 줄을 이을 때 넣는 문자. 잠정값.
    min_page_chars: 마지막 항목 뒤 페이지를 본문으로 볼 최소 글자 수 (공백 제외). 초기 제안값.
    page_number_center_tol: 쪽번호 줄로 볼 가로 중앙 허용 오차 (pt). 줄 가운데와 페이지 가운데의 거리가
        이 값 이하이면 가운데 정렬로 본다.
    """

    levels: list[str] = field(default_factory=lambda: list(DEFAULT_BODY_LEVELS))
    line_join: str = " "
    min_page_chars: int = 100
    page_number_center_tol: float = 10.0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.levels, list)
            or not self.levels
            or not all(isinstance(k, str) and k in BODY_LEVEL_KINDS for k in self.levels)
            or len(set(self.levels)) != len(self.levels)
        ):
            raise ValueError("levels: 정해진 번호 종류의 중복 없는 비어 있지 않은 목록이어야 한다")
        if not isinstance(self.line_join, str):
            raise ValueError("line_join: 문자열이어야 한다")
        if isinstance(self.min_page_chars, bool) or not isinstance(self.min_page_chars, int):
            raise ValueError("min_page_chars: 정수여야 한다")
        if self.min_page_chars < 0:
            raise ValueError("min_page_chars: 0 이상이어야 한다")
        tol = self.page_number_center_tol
        if isinstance(tol, bool) or not isinstance(tol, (int, float)) or tol < 0:
            raise ValueError("page_number_center_tol: 0 이상의 수여야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BodyConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ValueError(f"알 수 없는 body 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


@dataclass
class ChunkConfig:
    """실험군 청킹 설정.

    max_chunk_chars: 항목 + 하위 항목 전체가 이 글자 수 이하면 한 chunk, 넘으면 하위 항목 단위로 나눈다.
    path_label_chars: 계층 경로에 쓰는 항목 이름 (항목 첫 줄)과 표지 문서명의 최대 글자 수. 넘으면 자른다.
    """

    max_chunk_chars: int = 1000
    path_label_chars: int = 40

    def __post_init__(self) -> None:
        for name in ("max_chunk_chars", "path_label_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name}: 1 이상의 정수여야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChunkConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ValueError(f"알 수 없는 chunk 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


@dataclass
class BedrockConfig:
    """Bedrock 호출 설정. 자격증명은 두지 않는다 (환경 변수 AWS_BEARER_TOKEN_BEDROCK을 boto3가 읽는다).

    region, embed_model_id, answer_model_id: 비밀이 아닌 값. 코드에 기본값을 두지 않고 config.yaml에 적는다.
    max_attempts: 첫 시도를 포함한 총 시도 횟수 (throttling 재시도).
    answer_max_tokens, temperature: 답변 호출 설정. check-bedrock도 같은 값을 쓴다.
    """

    region: str = ""
    embed_model_id: str = ""
    answer_model_id: str = ""
    max_attempts: int = 5
    answer_max_tokens: int = 1024
    temperature: float = 0.0

    def __post_init__(self) -> None:
        for name in ("region", "embed_model_id", "answer_model_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name}: 비어 있지 않은 문자열이어야 한다")
        for name in ("max_attempts", "answer_max_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name}: 1 이상의 정수여야 한다")
        t = self.temperature
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 0 <= t <= 1:
            raise ValueError("temperature: 0 이상 1 이하의 수여야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BedrockConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ValueError(f"알 수 없는 bedrock 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


@dataclass
class AskConfig:
    """검색 설정.

    top_k: 벡터 검색으로 가져올 chunk 수 (표 후처리 전 기준).
    lexical_top_k: 벡터 결과 뒤에 붙일 낱말 검색 결과 수 (벡터 결과에 없는 것만). 0이면 벡터 검색만 쓴다.
    lexical_min_score: 낱말 검색 결과를 붙이는 BM25 점수 하한 (이 값 이상만). 0이면 하한 없음.
    """

    top_k: int = 5
    lexical_top_k: int = 3
    lexical_min_score: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValueError("top_k: 1 이상의 정수여야 한다")
        k = self.lexical_top_k
        if isinstance(k, bool) or not isinstance(k, int) or k < 0:
            raise ValueError("lexical_top_k: 0 이상의 정수여야 한다")
        m = self.lexical_min_score
        if isinstance(m, bool) or not isinstance(m, (int, float)) or m < 0:
            raise ValueError("lexical_min_score: 0 이상의 수여야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AskConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ValueError(f"알 수 없는 ask 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


@dataclass
class ChatConfig:
    """챗봇의 후속 질문 재작성 설정.

    history_turns: 질문을 재작성할 때 참고하는 최근 대화 턴 수.
    rewrite_answer_chars: 재작성 프롬프트에 넣는 이전 답변의 최대 글자 수 ("출처:" 이후는 빼고 앞부분만).
    """

    history_turns: int = 3
    rewrite_answer_chars: int = 300

    def __post_init__(self) -> None:
        for name in ("history_turns", "rewrite_answer_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name}: 1 이상의 정수여야 한다")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatConfig":
        """dict에서 생성한다. 없는 키는 기본값, 모르는 키는 ValueError."""
        known = {f.name for f in fields(cls)}
        unknown = [key for key in data if key not in known]
        if unknown:
            raise ValueError(f"알 수 없는 chat 설정 키가 {len(unknown)}개 있다")
        return cls(**data)


def _read_section(path: str, name: str) -> dict[str, Any] | None:
    """config.yaml의 최상위 섹션 하나를 읽는다. 파일이 비었거나 섹션이 없으면 None."""
    with open(path, encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError:
            # 라이브러리 메시지에는 파일 내용 일부가 들어가므로 버린다
            raise ValueError("설정 파일을 YAML로 해석할 수 없다") from None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("설정 파일 최상위는 매핑이어야 한다")
    section = raw.get(name)
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError(f"{name} 섹션은 매핑이어야 한다")
    return section


def load_config(path: str) -> TableConfig:
    """config.yaml을 읽어 table 섹션을 TableConfig로 만든다.

    - 파일이 비어 있거나 table 섹션이 없으면 기본값
    - table 섹션 밖의 다른 최상위 섹션은 다른 단계의 설정이므로 무시한다
    """
    table = _read_section(path, "table")
    return TableConfig() if table is None else TableConfig.from_dict(table)


def load_body_config(path: str) -> BodyConfig:
    """config.yaml의 body 섹션을 BodyConfig로 만든다. 섹션이 없으면 기본값."""
    body = _read_section(path, "body")
    return BodyConfig() if body is None else BodyConfig.from_dict(body)


def load_chunk_config(path: str) -> ChunkConfig:
    """config.yaml의 chunk 섹션을 ChunkConfig로 만든다. 섹션이 없으면 기본값."""
    chunk = _read_section(path, "chunk")
    return ChunkConfig() if chunk is None else ChunkConfig.from_dict(chunk)


def load_bedrock_config(path: str) -> BedrockConfig:
    """config.yaml의 bedrock 섹션을 BedrockConfig로 만든다. 섹션이 없으면 ValueError (리전, 모델은 기본값이 없다)."""
    bedrock = _read_section(path, "bedrock")
    return BedrockConfig.from_dict(bedrock or {})


def load_ask_config(path: str) -> AskConfig:
    """config.yaml의 ask 섹션을 AskConfig로 만든다. 섹션이 없으면 기본값."""
    ask = _read_section(path, "ask")
    return AskConfig() if ask is None else AskConfig.from_dict(ask)


def load_chat_config(path: str) -> ChatConfig:
    """config.yaml의 chat 섹션을 ChatConfig로 만든다. 섹션이 없으면 기본값."""
    chat = _read_section(path, "chat")
    return ChatConfig() if chat is None else ChatConfig.from_dict(chat)
