"""레이아웃 파서 (저장소의 parser/, pdfplumber-body-table-parser 보고서 모드)로 보고서를 읽어 ParsedReport 형식으로 바꾼다.

parse.parse_report가 부른다. 파서가 없거나 실패하면 LayoutParserError (이유 포함) — 처리 상태 error로 화면에 보인다.
파서가 더해 주는 것: 띄어쓰기 복원 (글자 간격·단어 중간 줄바꿈), 쪽번호·머리글·그림 안 이름표 제외, 『』 복원,
위첨자 각주 번호 분리, 장·절 제목 트리 (제목·개요·1.2·3.1 …), 병합 칸·쪽 넘김 표, 표 설명 ("[표1] …").

pages    쪽마다 "[p.N]\\n" + 본문 줄 (읽기 순서) + 쪽 끝 표 ("[표 p.N-k] 설명\\n| … |"). 모든 쪽 (표지·목차 포함).
         쪽을 넘어간 표는 첫 쪽에 한 번 붙이고 "(p.11~14)"를 적는다.
sections facts, timeline, analysis, conclusion, findings, causes, recommendations — 제목 트리에서 찾은 장·절의
         하위 내용 전체 ([p.N] 표시, 표 포함). 트리에서 못 찾은 것은 parse.split_sections (정규식) 결과로 채운다.

환경 변수: PARSER_DIR (기본: 저장소의 parser/), LAYOUT_PARSER_TIMEOUT (초, 기본 900).
작업 폴더: PDF 옆 layout_<PDF 이름>/ (in/ 입력 복사본, docs/ 문서 설정, out/ 파서 결과). 같은 PDF를 다시 읽으면 새로 만든다.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from itertools import groupby
from pathlib import Path

PARSER_DIR = Path(os.getenv("PARSER_DIR", Path(__file__).resolve().parents[2] / "parser"))
DOC_ID = "report"  # 작업 폴더 안 입력 파일 이름 (report.pdf) = 파서 doc_id

# 백엔드 섹션 키 → 제목 트리에서 찾을 말 (공백·번호 뺀 제목). (키, 찾을 말, 부모 키)
SECTION_RULES = [
    ("facts", ("사실정보",), None),
    ("analysis", ("분석",), None),
    ("conclusion", ("결론",), None),
    ("recommendations", ("안전권고", "권고"), None),
    ("timeline", ("경위",), "facts"),
    ("findings", ("조사결과",), "conclusion"),
    ("causes", ("사고원인", "원인"), "conclusion"),
]


class LayoutParserError(RuntimeError):
    """레이아웃 파서를 돌리지 못했거나 결과를 읽지 못함. 메시지가 처리 상태 error의 이유로 화면에 나온다."""


def _textjoin():
    """파서의 줄바꿈 잇기 모듈 (parser/parsing/textjoin.py). 다른 파서 모듈과 이름이 겹치지 않게 파일로 읽는다."""
    spec = importlib.util.spec_from_file_location("layout_textjoin", PARSER_DIR / "parsing" / "textjoin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_parser(pdf_path: Path) -> Path | None:
    """파서를 돌리고 결과 폴더 (out/secure/report/)를 돌려준다. 실패하면 LayoutParserError."""
    if not (PARSER_DIR / "parsing" / "run.py").exists():
        raise LayoutParserError(f"레이아웃 파서가 없습니다: {PARSER_DIR} (PARSER_DIR 확인)")
    # 파서는 cwd=PARSER_DIR로 돌기 때문에, 상대경로를 그대로 넘기면 작업 폴더가 parser/ 아래로 잘못 잡힌다.
    pdf_path = Path(pdf_path).resolve()
    work = pdf_path.parent / f"layout_{pdf_path.stem}"
    if work.exists():
        shutil.rmtree(work)
    (work / "in").mkdir(parents=True)
    shutil.copy2(pdf_path, work / "in" / f"{DOC_ID}.pdf")
    env = {**os.environ, "PARSE_DATA_DIR": str(work / "in"), "PARSE_OUT_DIR": str(work / "out"),
           "PARSE_DOCS_DIR": str(work / "docs"), "PARSE_PROFILE": "report", "PARSE_FONT_SAMPLE_PAGES": "40"}
    env.pop("PARSE_DOC", None)
    # 파서는 별도 프로세스라, 지금 프로세스가 찾는 패키지 경로를 그대로 넘긴다.
    # (Vercel 함수는 설치한 패키지 폴더를 실행 중에 sys.path로만 더하므로, 넘기지 않으면 새 프로세스가 yaml 등을 못 찾는다)
    env["PYTHONPATH"] = os.pathsep.join([p for p in sys.path if p] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    try:
        proc = subprocess.run([sys.executable, str(PARSER_DIR / "parsing" / "run.py"), "--skip", "render,leak"],
                              cwd=PARSER_DIR, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=int(os.getenv("LAYOUT_PARSER_TIMEOUT", "900")))
    except subprocess.TimeoutExpired:
        raise LayoutParserError(f"레이아웃 파서 시간 초과 ({os.getenv('LAYOUT_PARSER_TIMEOUT', '900')}초)")
    sec = work / "out" / "secure" / DOC_ID
    if proc.returncode != 0 or not (sec / "tree" / "nodes.jsonl").exists():
        tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-8:])
        print(f"[layout_parser] 실패 (rc={proc.returncode}): {pdf_path.name}\n{tail}", file=sys.stderr)
        raise LayoutParserError(f"레이아웃 파서 실패 (rc={proc.returncode}): {tail[-500:]}")
    return sec


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()] if path.exists() else []


def table_md(rows: list[list]) -> str:
    rows = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rows if any((c or "").strip() for c in r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _table_block(t: dict, label: str) -> str:
    md = table_md(t["header"] + t["rows"])
    if not md:
        return ""
    title = (t.get("title") or {}).get("text", "")
    span = f" (p.{t['pages'][0]}~{t['pages'][-1]})" if len(t["pages"]) > 1 else ""
    return f"[{label}]{(' ' + title) if title else ''}{span}\n{md}"


def build_pages(sec: Path, tables: list[dict]) -> list[str]:
    """쪽별 글자: 덤프 줄 (읽기 순서) 중 쪽번호·제외 (머리글·그림 이름표)·표 칸 줄을 빼고, 표는 쪽 끝에 Markdown으로."""
    by_page = sec / "lines" / "by_page"
    n = max(int(p.stem[1:]) for p in by_page.glob("p*.json"))
    marked = {(d["page"], d["line_id"]): d for d in _jsonl(sec / "lines" / "lines_marked.jsonl")}
    regs = _jsonl(sec / "tables" / "table_regions.jsonl")
    table_src = {r["source"] for r in regs if r.get("decided") == "table"}
    pages = []
    for p in range(1, n + 1):
        f = by_page / f"p{p:03d}.json"
        lines = json.loads(f.read_text(encoding="utf-8"))["lines"] if f.exists() else []
        keep = []
        for d in sorted(lines, key=lambda d: d["line_id"]):
            m = marked.get((p, d["line_id"]))
            if d.get("is_page_number") or (m and m["excluded"]):
                continue
            if d.get("region_id") in table_src and d.get("zone") == "table":
                continue
            if d["text"].strip():
                keep.append(d["text"].strip())
        text = "\n".join(keep)
        for k, t in enumerate([t for t in tables if t["pages"][0] == p], start=1):
            block = _table_block(t, f"표 p.{p}-{k}")
            if block:
                text += f"\n\n{block}"
        pages.append(f"[p.{p}]\n{text}")
    return pages


def build_sections(nodes: list[dict], tables: list[dict], tj) -> dict[str, str]:
    """제목 트리에서 백엔드 섹션을 찾아 하위 내용을 [p.N] 표시와 함께 글자로."""
    byid = {n["id"]: n for n in nodes}
    tbl = {t["table_id"]: t for t in tables}
    vocab = tj.Vocab(x["text"] for n in nodes for x in n["lines"] + n["title_lines"])
    heads = [n for n in nodes if n["type"] == "heading"]

    def bare(n):
        return re.sub(r"\s", "", re.sub(r"^[\sⅠ-Ⅹ\d.()]+", "", n["title"] or ""))

    def under(n, anc_id):
        while n is not None:
            if n["id"] == anc_id:
                return True
            n = byid.get(n["parent_id"])
        return False

    found: dict[str, dict] = {}
    for key, words, parent in SECTION_RULES:
        for w in words:
            cands = [h for h in heads if w in bare(h) and (parent is None or parent not in found or under(h, found[parent]["id"]))]
            exact = [h for h in cands if bare(h) == w or bare(h).startswith(w)]
            pool = exact or cands
            if pool:
                found[key] = min(pool, key=lambda h: (h["level"], nodes.index(h)))
                break

    def render(n, out, state):
        for group in (n["title_lines"], n["lines"]):
            for page, seg in groupby(group, key=lambda x: x["page"]):
                if page != state["page"]:
                    out.append(f"[p.{page}]")
                    state["page"] = page
                out.append(tj.join_lines([x["text"] for x in seg], vocab))
        for tid in n.get("tables", []):
            t = tbl.get(tid)
            block = _table_block(t, "표") if t else ""
            if block:
                if t["pages"][0] != state["page"]:
                    out.append(f"[p.{t['pages'][0]}]")
                    state["page"] = t["pages"][0]
                out.append(block)
        for c in n["children"]:
            render(byid[c], out, state)

    sections = {}
    for key, h in found.items():
        out: list[str] = []
        render(h, out, {"page": None})
        sections[key] = "\n".join(x for x in out if x)
    return sections


def parse_with_layout(pdf_path: str | Path) -> tuple[list[str], dict[str, str]]:
    """(pages, sections). 실패하면 LayoutParserError."""
    sec = run_parser(Path(pdf_path))
    try:
        nodes = _jsonl(sec / "tree" / "nodes.jsonl")
        tables = _jsonl(sec / "tables" / "tables.jsonl")
        pages = build_pages(sec, tables)
        sections = build_sections(nodes, tables, _textjoin())
    except Exception as e:
        raise LayoutParserError(f"레이아웃 파서 결과 변환 실패: {type(e).__name__}: {e}") from e
    return pages, sections
