"""누출 검사. PDF 문자에서 공백을 뺀 15자 창의 해시 집합을 secure에 만들고,
secure·data·venv 밖의 텍스트 파일에 같은 창이 있는지 검사한다.

실행 (requirements.txt 환경):
  python parsing/leak_check.py build   # 해시 집합 생성 (문서마다 한 번, secure/<doc_id>/leak_hashes.bin)
  python parsing/leak_check.py check   # 검사. 일치 0건이면 exit 0
창은 두 순서로 만든다: pdfplumber 글자 순서 그대로, 1week-rag _group_lines의 줄 순서.
일치하면 파일·줄·열만 출력한다 (글자는 출력하지 않는다).
"""

import hashlib
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safeio import ROOT, SECURE, Trusted, out, secure_path, setup  # noqa: E402

WINDOW = 15
HASH_FILE = SECURE / "leak_hashes.bin"
SKIP_DIRS = {"secure", "data", "review", ".venv", "__pycache__"}  # review/는 원문 확인용
TEXT_EXT = {".md", ".csv", ".json", ".jsonl", ".log", ".txt", ".py", ".html", ".yaml", ".yml", ".tsv"}


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "little")


def _windows(text: str) -> list[str]:
    t = "".join(text.split())
    return [t[i : i + WINDOW] for i in range(len(t) - WINDOW + 1)]


def build() -> int:
    import pdfplumber

    sys.path.insert(0, str(ROOT / "vendor"))  # 1주차 표 파서 복사본
    from policy_rag.ingest.extract import Char
    from policy_rag.ingest.tables import _group_lines

    from config import doc_pdf

    pdf_path = doc_pdf()
    hashes: set[int] = set()
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            chars = [Char(str(c["text"]), float(c["x0"]), float(c["x1"]), float(c["top"]), float(c["bottom"]))
                     for c in page.chars]
            raw = "".join(c.text for c in chars)
            lined = "".join("".join(c.text for c in g) for g in _group_lines(chars))
            for text in (raw, lined):
                hashes.update(_h(w) for w in _windows(text))
            page.flush_cache()
            if i % 100 == 0:
                out("build_progress", page=i, of=n, n_hashes=len(hashes))
    arr = array("Q", sorted(hashes))
    with open(secure_path(HASH_FILE), "wb") as f:
        arr.tofile(f)
    out("build_done", pages=n, n_hashes=len(arr), window=WINDOW)
    return 0


def _kind(w: str) -> str:
    """일치한 창의 문자 종류 (글자는 내보내지 않는다)."""
    if not w.isascii():
        return "non_ascii"
    if any(c.isalpha() for c in w):
        return "ascii_letters"
    if any(c.isdigit() for c in w):
        return "ascii_digit_punct"
    return "ascii_punct_only"


def _targets() -> list[Path]:
    files = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_file() and p.suffix.lower() in TEXT_EXT:
            files.append(p)
    return sorted(files)


def check() -> int:
    if not HASH_FILE.exists():
        out("check_error", reason="hash_file_missing")
        return 2
    arr = array("Q")
    with open(HASH_FILE, "rb") as f:
        arr.frombytes(f.read())
    hashes = set(arr)
    n_hits = 0
    files = _targets()
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        # 공백을 뺀 글자 위치 -> 원래 (줄, 열)
        pos: list[tuple[int, int]] = []
        chars: list[str] = []
        line, col = 1, 0
        for ch in text:
            if ch == "\n":
                line, col = line + 1, 0
                continue
            col += 1
            if not ch.isspace():
                chars.append(ch)
                pos.append((line, col))
        t = "".join(chars)
        hit_lines: dict[int, int] = {}
        kinds: dict[str, int] = {}
        for i in range(len(t) - WINDOW + 1):
            w = t[i : i + WINDOW]
            if len(set(w)) > 1 and _h(w) in hashes:  # 한 글자 반복 창 (구분선 등)은 정보가 없어 제외
                hit_lines[pos[i][0]] = hit_lines.get(pos[i][0], 0) + 1
                k = _kind(w)
                kinds[k] = kinds.get(k, 0) + 1
        if hit_lines:
            n = sum(hit_lines.values())
            n_hits += n
            out("leak_hit", file=Trusted(str(p.relative_to(ROOT))), windows=n, kinds=kinds,
                lines=sorted(hit_lines)[:20])
    out("check_done", files=len(files), hit_windows=n_hits, result="PASS" if n_hits == 0 else "FAIL")
    return 0 if n_hits == 0 else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    setup(f"leak_check_{mode}")
    return build() if mode == "build" else check()


if __name__ == "__main__":
    sys.exit(main())
