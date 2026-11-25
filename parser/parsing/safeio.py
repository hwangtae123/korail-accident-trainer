"""공용 출력 helper. 모든 4주차 스크립트(즉석 확인 포함)는 출력을 이 모듈로만 낸다.

- out(): 표준 출력과 results/logs/<name>.log에 쓴다. 값은 수치, bool, None, ASCII 라벨 문자열, Trusted
  (파일 이름처럼 원문이 아닌 것으로 확인된 문자열)만 허용한다. 한글 원문은 형식상 통과할 수 없다.
- describe(): 구조만 보여 준다. 문자열은 <str len=N>, 허용한 라벨 키만 값 분포를 보인다.
- setup(): fd 1·2를 secure/logs/<name>.lib.log로 돌린다 (라이브러리 출력은 원문이 있을 수 있으므로 secure로).
  예외는 타입과 parsing/ 안 파일:줄만 출력한다 (메시지는 내보내지 않는다).
- secure_path(): 원문을 쓰는 경로가 secure/ 아래인지 확인한다.
"""

import datetime
import os
import re
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# 문서마다 산출물 폴더를 나눈다: secure/<doc_id>/, results/<doc_id>/, review/<doc_id>/.
# 처리할 문서는 환경 변수 PARSE_DOC (doc_id). 없으면 기본 문서 (run.py는 data/의 PDF마다 PARSE_DOC를 넘긴다).
DEFAULT_DOC = "allinone_cancer_2_0"
DOC_ID = os.environ.get("PARSE_DOC") or DEFAULT_DOC


def _paths() -> tuple[Path, Path, Path]:
    """PDF 폴더, 결과 폴더, 문서 설정 폴더. 환경 변수 PARSE_DATA_DIR·PARSE_OUT_DIR·PARSE_DOCS_DIR, 없으면
    config/paths.yaml의 data_dir·out_dir·docs_dir (파서 폴더 기준 상대 경로), 없으면 파서 폴더 안 data/, 파서 폴더
    (secure/, results/, review/가 그 아래), config/docs/."""
    cfg = {}
    f = ROOT / "config" / "paths.yaml"
    if f.exists():
        import yaml

        cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}

    def pick(env: str, key: str, default: Path) -> Path:
        v = os.environ.get(env) or cfg.get(key)
        return (ROOT / v).resolve() if v else default

    return (pick("PARSE_DATA_DIR", "data_dir", ROOT / "data"), pick("PARSE_OUT_DIR", "out_dir", ROOT),
            pick("PARSE_DOCS_DIR", "docs_dir", ROOT / "config" / "docs"))


DATA_DIR, OUT_DIR, DOCS_DIR = _paths()
SECURE_ROOT = OUT_DIR / "secure"
RESULTS_ROOT = OUT_DIR / "results"
SECURE = SECURE_ROOT / DOC_ID
RESULTS = RESULTS_ROOT / DOC_ID
LOG_DIR = RESULTS / "logs"
SECURE_LOG_DIR = SECURE / "logs"

_SAFE = re.compile(r"^[A-Za-z0-9_./:+\-=%#@<>\[\]() ,|*]{0,64}$")

_real_out = None
_log_file = None


class Trusted(str):
    """원문이 아닌 것으로 확인한 문자열 (PDF 파일 이름, 경로, 기기 이름). 감싸는 쪽이 책임진다."""


class UnsafeValue(TypeError):
    pass


def _check(value: Any, where: str = "value") -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Trusted):
        return str(value)
    if isinstance(value, str):
        if _SAFE.match(value):
            return value
        raise UnsafeValue(f"unsafe string at {where} (len={len(value)})")
    if isinstance(value, (list, tuple)):
        return [_check(v, where) for v in value]
    if isinstance(value, dict):
        return {_check(k, where + ".key"): _check(v, where) for k, v in value.items()}
    if type(value).__module__ == "numpy":
        return _check(value.item() if getattr(value, "ndim", 1) == 0 else value.tolist(), where)
    raise UnsafeValue(f"unsupported type at {where}: {type(value).__name__}")


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, list):
        return "[" + ",".join(_fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}:{_fmt(x)}" for k, x in v.items()) + "}"
    return str(v)


def _emit(line: str) -> None:
    stream = _real_out or sys.__stdout__
    stream.write(line + "\n")
    stream.flush()
    if _log_file is not None:
        _log_file.write(line + "\n")
        _log_file.flush()


def out(event: str, **fields: Any) -> None:
    """한 줄 출력: event k=v ... 값이 허용 형식이 아니면 그 필드만 <blocked>로 바꾼다."""
    parts = [_check(event, "event")]
    for k, v in fields.items():
        try:
            parts.append(f"{_check(k, 'key')}={_fmt(_check(v, k))}")
        except UnsafeValue:
            parts.append(f"{k}=<blocked>")
    _emit(" ".join(parts))


def _shape(values: list[Any], label_keys: frozenset[str], key: str | None) -> dict[str, Any]:
    types = Counter(type(v).__name__ for v in values)
    res: dict[str, Any] = {"n": len(values), "type": dict(types) if len(types) > 1 else next(iter(types), "none")}
    strs = [v for v in values if isinstance(v, str)]
    if strs:
        lens = [len(s) for s in strs]
        res["str_len"] = [min(lens), max(lens)]
        if key in label_keys:
            res["values"] = {(s if _SAFE.match(s) else f"<str len={len(s)}>"): c for s, c in Counter(strs).items()}
    nums = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if nums and key in label_keys:
        res["values"] = dict(Counter(nums))
    dicts = [v for v in values if isinstance(v, dict)]
    if dicts:
        keys: dict[str, list[Any]] = {}
        for d in dicts:
            for k, v in d.items():
                sk = k if isinstance(k, str) and _SAFE.match(k) else f"<key len={len(str(k))}>"
                keys.setdefault(sk, []).append(v)
        res["keys"] = {k: _shape(vs, label_keys, k) for k, vs in keys.items()}
    lists = [v for v in values if isinstance(v, (list, tuple))]
    if lists:
        lens = [len(v) for v in lists]
        res["list_len"] = [min(lens), max(lens)]
        flat = [x for v in lists for x in v]
        if flat:
            res["items"] = _shape(flat, label_keys, key)
    arrays = [v for v in values if type(v).__module__ == "numpy" and hasattr(v, "shape")]
    if arrays:
        res["shapes"] = sorted({str(tuple(a.shape)) for a in arrays})[:5]
    return res


def describe(obj: Any, label_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    """obj의 구조 (키, 타입, 개수, 문자열 길이 범위). label_keys에 있는 키만 값 분포를 보인다."""
    return _shape([obj], frozenset(label_keys), None)


def out_describe(name: str, obj: Any, label_keys: tuple[str, ...] = ()) -> None:
    """describe 결과를 들여쓴 줄로 출력한다."""

    def walk(node: dict[str, Any], path: str) -> None:
        info = {k: v for k, v in node.items() if k not in ("keys", "items")}
        out("describe", path=Trusted(path), **info)
        for k, child in node.get("keys", {}).items():
            walk(child, f"{path}.{k}")
        if "items" in node:
            walk(node["items"], f"{path}[]")

    walk(describe(obj, label_keys), name)


def secure_path(path: str | os.PathLike[str]) -> Path:
    """원문이 들어가는 출력 경로를 확인하고 상위 폴더를 만든다. secure 밖이면 예외."""
    p = Path(path).resolve()
    if SECURE.resolve() not in p.parents:
        raise UnsafeValue("source-bearing output must be under secure/")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def result_path(path: str | os.PathLike[str]) -> Path:
    """원문 없는 결과 경로 (secure·data 밖). 상위 폴더를 만든다."""
    p = Path(path).resolve()
    if SECURE_ROOT.resolve() in p.parents or DATA_DIR.resolve() in p.parents:
        raise UnsafeValue("result path must be outside secure/ and data/")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


REVIEW = OUT_DIR / "review" / DOC_ID


def rel(path: str | os.PathLike[str]) -> str:
    """화면 표시용 경로: 파서 폴더 기준 상대 경로 (밖이면 ../로, 다른 드라이브면 절대 경로)."""
    try:
        return Path(os.path.relpath(Path(path).resolve(), ROOT.resolve())).as_posix()
    except ValueError:
        return str(path)
REVIEW_MAX_LINES = 200


def _review_index(name: str, question: str) -> None:
    """review/INDEX.md를 갱신한다 (파일 이름 -> 답하려는 질문). 목록은 review/_index.json에 둔다."""
    import json

    idx_path = REVIEW / "_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    idx[name] = question
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = ["# review/ 목록", "",
            "직접 열어 볼 수 있는 확인용 파일. 와이어프레임 (선·상자만)과 구조 정보 (수치·좌표·라벨)만 둔다. "
            "원문 발췌·쪽 렌더는 secure/review/ (무작위 15쪽 제외, 파일당 200줄 이내).", "",
            "| 파일 | 답하려는 질문 |", "|---|---|"]
    rows += [f"| `{k}` | {v} |" for k, v in sorted(idx.items())]
    (REVIEW / "INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _check_review_pages(pages, images: bool) -> None:
    from samples import RANDOM15, SAMPLE45

    pages = set(pages)
    if pages & set(RANDOM15):
        raise UnsafeValue("random15 pages are not allowed in review/")
    if images and not pages <= set(SAMPLE45):
        raise UnsafeValue("review images are allowed only for sample45 pages")


def review_prune_index() -> None:
    """review/_index.json에서 파일이 없는 항목을 빼고 INDEX.md를 다시 쓴다 (<...>·NNN 묶음 항목은 폴더가 있으면 남김)."""
    import json

    idx_path = REVIEW / "_index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    keep = {k: v for k, v in idx.items()
            if (REVIEW / k).exists() or (("NNN" in k or "<" in k) and (REVIEW / k.split("/")[0]).is_dir())}
    idx_path.write_text("{}", encoding="utf-8")
    for k, v in keep.items():
        _review_index(k, v)


def secure_review_write(name: str, rows: list[str]) -> Path:
    """원문 발췌가 들어가는 사람 확인용 파일은 secure/review/에만 쓴다 (Claude는 열지 않는다)."""
    p = secure_path(SECURE / "review" / name)
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


def secure_review_image_path(rel: str) -> Path:
    """원문이 보이는 이미지 (쪽 렌더 위에 그린 것)는 secure/review/에만 둔다."""
    return secure_path(SECURE / "review" / rel)


def review_write(name: str, rows: list[str], question: str, pages) -> Path:
    """구조 정보 (수치·좌표·라벨, 원문 없음) 파일을 review/에 쓴다. 200줄 넘거나 무작위 15쪽이 섞이면 예외."""
    _check_review_pages(pages, images=False)
    if len(rows) > REVIEW_MAX_LINES:
        raise UnsafeValue(f"review file over {REVIEW_MAX_LINES} lines ({len(rows)})")
    p = REVIEW / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    _review_index(name, question)
    return p


def review_wireframe_path(rel: str, page: int, index_key: str, question: str) -> Path:
    """와이어프레임 (선·상자만, 글자 없음) 이미지의 review/ 경로. 원문이 없어 샘플 45쪽 밖도 되지만 무작위 15쪽은 막는다."""
    _check_review_pages([page], images=False)
    p = REVIEW / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    _review_index(index_key, question)
    return p


def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
    frames = [
        f"{Path(f.filename).name}:{f.lineno}"
        for f in traceback.extract_tb(tb)
        if Path(f.filename).resolve().parent in (Path(__file__).resolve().parent, ROOT / "chunking", ROOT / "indexing", ROOT / "qa")
    ]
    _emit(f"ERROR type={exc_type.__name__} at={'>'.join(frames) or 'library'} (message suppressed)")
    if _log_file is not None:
        _log_file.close()
    # 전체 traceback은 secure 로그에만 남긴다 (원문이 들어 있을 수 있음)
    traceback.print_exception(exc_type, exc, tb, file=sys.stderr)


def review_mode() -> bool:
    """확인용 출력 (수치 리포트·원문 발췌·와이어프레임·확인 그림)을 만들지. 기본은 끄고 청킹에 필요한 결과만 만든다.
    켜기: 스크립트 인자 --review, 또는 환경 변수 PARSE_REVIEW=1 (run.py --review가 단계마다 넘긴다)."""
    return "--review" in sys.argv or os.environ.get("PARSE_REVIEW") == "1"


def setup(name: str, shared: bool = False) -> None:
    """스크립트 시작 때 한 번 부른다. 라이브러리 출력은 secure 로그로, out()은 실제 표준 출력으로.
    shared=True: 문서 하나에 묶이지 않는 스크립트 (run.py 전체 실행)는 secure/logs/, results/logs/에 쓴다."""
    global _real_out, _log_file
    if not _SAFE.match(name):
        raise UnsafeValue("bad script name")
    secure_logs = (SECURE_ROOT / "logs") if shared else SECURE_LOG_DIR
    result_logs = (RESULTS_ROOT / "logs") if shared else LOG_DIR
    secure_logs.mkdir(parents=True, exist_ok=True)
    result_logs.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    real_fd = os.dup(1)
    _real_out = os.fdopen(real_fd, "w", encoding="utf-8", errors="replace")
    lib_log = open(secure_logs / f"{name}.lib.log", "a", encoding="utf-8", errors="replace")
    os.dup2(lib_log.fileno(), 1)
    os.dup2(lib_log.fileno(), 2)
    sys.stdout = lib_log
    sys.stderr = lib_log
    _log_file = open(result_logs / f"{name}.log", "a", encoding="utf-8")
    sys.excepthook = _excepthook
    out("start", script=name, at=datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
