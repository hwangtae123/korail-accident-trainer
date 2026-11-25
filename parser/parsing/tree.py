"""4단계: 본문 트리.

포함 쪽의 줄 (제외·쪽번호 아님)을 읽기 순서 (쪽, top, x0)로 훑으며 노드를 만든다. 표 (2단계)와 박스 블록 (3단계)은
첫 쪽 위치에 한 항목으로 끼워 넣고, 그 영역의 줄과 표 아래 주석 줄은 트리 줄에서 뺀다 (이미 표·박스에 들어 있음).

단계 (위에서 아래):
  zone (구역, config/docs/<doc_id>.yaml zones) > contract (제목 띠: 약관명·특약명) > pyeon (편, 프로필 pyeon_title + 편 패턴)
  / section (프로필 section_title, 패턴 없는 굵은 12pt 제목) > gwan (관) > article (조: 프로필 article_title + 조 패턴,
  "제N조", "제N-M조", 가지 조 "…조의M") > 항목 (줄 맨 앞 번호 패턴).
항목 단계는 고정하지 않는다: 새 번호 패턴이 현재 조 안 스택에 이미 있으면 그 노드의 형제, 없으면 현재 노드의 자식
(①, 1., 가., 1), 가), (1), (가), 글머리표 순서가 문서마다 달라도 됨). 형제는 번호가 바로 이어지는 후보를 먼저 고른다
(place_item). 줄바꿈된 문장 조각 ("…합니" 다음 줄 "다. …")은 글자에 이어 붙인다.
주석 (※, (주), ㈜)은 안쪽 목록을 가질 수 있다 ("㈜ 1. …"이면 주석 아래 1번 항목). 굵은 줄 (article_title 폰트인데 조 패턴
없음)과 문단 (굵은 줄 다음 보통 줄)은 잎: 다음 번호 줄이 오면 닫는다.
줄 패턴은 덤프 뒤에 추가한 패턴을 반영하려고 pdf_lines.line_pattern으로 다시 계산한다.
제목 이어짐: 조·편·관·절 제목 줄 바로 다음 (사이에 다른 항목 없음, 세로 간격 tree.title_cont_gap_ratio × 줄 높이 이내)의
같은 폰트 패턴 없는 줄은 제목의 둘째 줄.
번호 없는 보통 줄은 현재 노드 글자에 이어 붙인다 (1week cell_line_join).
표·박스 블록은 현재 가장 깊은 잎 아닌 노드의 자식 (바로 앞 조·항·호). article_id = 가장 가까운 조 조상.

보고서 모드 (프로필 mode: report, 장·절 번호 보고서): 편·관·조 대신 제목 (heading) 노드를 쓴다.
  제목 = 줄 전체가 다음에 맞는 줄: "Ⅱ. 사실정보" (로마 숫자, 단계 0), "1. 사실정보"·"1.2 피해사항"·"2.4.5.1 …"
  (소수점 번호, 단계 = 번호 개수), 번호 없는 제목 (프로필 report.unnumbered_headings, 단계 1). 소수점 번호는
  (a) 번호 흐름이 맞고 (직전 제목 1.2 다음은 1.2.1 / 1.3(·1.4) / 2.(·3.)만, 로마 숫자 제목 뒤에는 1.부터 다시),
  (b) 숫자 하나 번호 ("3.")만: 위 줄과 세로 간격 >= tree.report_heading_gap_ratio x 줄 높이 (쪽 첫 줄·표 다음은
  통과), (c) 글자 수 <=
  report.heading_max_chars, 문장 끝 ("다.")이 아님, (d) 줄이 본문 오른쪽 끝까지 차지 않음 (찬 줄은 줄바꿈된 문단의
  첫 줄), (e) " : " 이 없음 ("1. 운영기관 : 서울메트로" 같은 개요 항목)일 때만 제목. 아니면 기존 항목 규칙 (1. 목록 등).
  번호 문단: 제목이 아닌 "3.1.1 사고열차는 …"처럼 현재 제목 번호 아래 번호 (3.1 아래 3.1.x)로 시작하는 줄은
  항목 (marker decimal)으로 제목 아래에 둔다 (조사결과·안전권고의 번호 문단).
  제목 아래 번호 없는 글은 제목 노드 글자 (text)로, 번호 줄 (①, 1), (1), 가.)은 항목으로 붙는다.
  각주: 본문보다 작은 글씨이고 1)·(1)로 시작하는 줄은 note (marker footnote). 뒤따르는 작은 글씨 줄은 그 각주에 잇는다.
  각주는 본문에서 그 번호가 위첨자로 나온 노드 (덤프 footnote_refs)에 붙인다 (attached_by ref, 못 찾으면 position).
  그림·표 설명 줄 (프로필 caption_patterns): 표에 붙은 것 (tables.jsonl caption)은 빼고, 나머지는 가장 가까운 제목 아래
  caption 노드 (kind figure|table, number).
  목차 점선 줄 (report.toc_leader)은 버린다. 모든 노드에 heading_id (가장 가까운 제목)와 heading_path (제목 이름 목록).
  머리글 장 이름: 쪽 머리글 (exclude가 header로 뺀 줄, 예 "개요 한국철도공사 …")에서 문서 제목 (머리글끼리 같은 끝 부분)을
  뺀 글자가 번호 없는 제목 (개요·제목 …)이면 그 쪽 첫 줄 앞에 그 제목을 만든다 (본문에 제목 줄 없이 머리글에만 있는 장:
  사고 요약 카드 "제목", 원인 요약 "개요"). 본문에 같은 이름 줄이 또 나오면 버린다.
  제목 바로 다음 제목 줄은 간격 검사 (b)를 하지 않는다.

출력: secure/tree/nodes.jsonl (평평한 노드, parent_id·depth·path), secure/tree/attachments.jsonl (표·박스 → 노드),
      secure/tree/refs.jsonl (조·항·호·목 참조와 별표·유첨 인용, parsing/refs.py. 형식은 docs/refs_schema.md),
      secure/boxes/glossary.jsonl의 소속 조항 갱신 (parent_article)
번호 흐름 검사와 확인용 출력 (--review, parsing/review/tree.py): results/parsing/tree_report.md (수치만),
      review/tree_structure.md (구조 수치), secure/review/tree_outline.md + secure/review/tree_articles.md +
      secure/review/tree_spots.md·tree_spots/*.png (사람 확인용)
실행 (requirements.txt 환경): python parsing/tree.py
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import P, caption_kind, font, fonts_of, mode, profile  # noqa: E402
from pdf_lines import line_pattern, load_week1  # noqa: E402
from safeio import OUT_DIR, RESULTS, SECURE, out, review_mode, secure_path, setup  # noqa: E402
from samples import INCLUDED_PAGES, zone_of  # noqa: E402
from refs import extract_refs, link_citations  # noqa: E402
from textjoin import Vocab, join_lines  # noqa: E402

TREE_DIR = SECURE / "tree"
FIG_DIR = SECURE / "figures"
ITEM_PATTERNS = ("circled", "num_dot", "hangul_dot", "num_paren", "hangul_paren", "paren_num", "paren_hangul", "bullet")
NOTE_PATTERNS = ("note_ref", "note_ju", "note_cju")
NOTE_RE = {"note_ref": re.compile(r"※\s*"), "note_ju": re.compile(r"\(\s*주\s*\)\s*"), "note_cju": re.compile(r"㈜\s*")}
LEVEL = {"zone": 0, "contract": 1, "pyeon": 2, "section": 2, "gwan": 3, "article": 4, "heading": 2}
LEAVES = ("note", "bold", "para")
# 가지 조 "…조의M". PDF 글자 층에서 "의"가 빠져 "…조M"으로 읽히는 줄도 있어 (p192), 조 바로 뒤 숫자도 가지 번호로 본다
ART_RE = re.compile(r"\s*제\s*(\d+)\s*(?:-\s*(\d+)\s*)?조(?:\s*의\s*(\d+)|(\d+))?")
HANGUL_ORDER = "가나다라마바사아자차카타파하"
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"


def lvl(n: dict) -> int:
    """스택에서 닫는 순서 단계. 보고서 제목은 2 + 제목 단계 (로마 숫자 0, "1." 1, "1.1" 2 …)."""
    return 2 + n["level"] if n["type"] == "heading" else LEVEL.get(n["type"], 9)


class ReportHeadings:
    """보고서 모드 제목 찾기 (번호 모양 + 번호 흐름 + 위 간격)."""
    NUM_RE = re.compile(r"(\d+(?:\.\d+)*)\.?\s+(\S.*)")
    ROMAN_RE = re.compile(r"([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\.?\s*(\S.*)")

    def __init__(self, page_chapter: dict | None = None):
        rp = profile().get("report") or {}
        self.page_chapter = page_chapter or {}
        self.label: str | None = None  # 지금 번호 없는 제목 이름 (같은 이름 줄이 또 나오면 버림)
        self.page = None
        self.max_chars = rp.get("heading_max_chars", 60)
        self.unnumbered = {re.sub(r"\s", "", w) for w in rp.get("unnumbered_headings") or []}
        self.leader = re.compile(rp.get("toc_leader") or r"[·.…]{4,}")
        self.path: list[int] = []
        self.roman = 0

    def is_leader(self, text: str) -> bool:
        return bool(self.leader.search(text))

    @staticmethod
    def bare(text: str) -> str:
        """공백과 끝 괄호 ("개요(Synopsis)") 뺀 글자."""
        return re.sub(r"\(.*\)$", "", re.sub(r"\s", "", text))

    def page_label(self, page: int) -> str | None:
        """이 쪽에서 새로 시작하는 머리글 장 이름 (번호 없는 제목일 때만)."""
        lab = self.page_chapter.get(page)
        if lab and lab in self.unnumbered and lab != self.label:
            self.label, self.path = lab, []
            return lab
        return None

    def is_label_line(self, text: str) -> bool:
        return self.label is not None and self.bare(text) == self.label

    def _next_ok(self, nums: list[int]) -> bool:
        p = self.path
        if not p:
            return len(nums) == 1 and nums[0] in (1, 2)
        if nums == p + [1]:
            return True
        return any(len(nums) == k + 1 and nums[:k] == p[:k] and p[k] < nums[k] <= p[k] + 2 for k in range(len(p)))

    def para_number(self, text: str) -> list[int] | None:
        """제목이 아닌 번호 문단: 현재 제목 번호 바로 아래 번호 (3.1 아래 3.1.x)로 시작하면 그 번호."""
        m = self.NUM_RE.match(text.strip())
        if not m or not self.path:
            return None
        nums = [int(x) for x in m.group(1).split(".")]
        return nums if len(nums) == len(self.path) + 1 and nums[:-1] == self.path else None

    def match(self, text: str, gap_ok: bool, wide: bool = False) -> tuple[int, list | None, str] | None:
        """(단계, 번호, 제목 글자) 또는 None. 맞으면 번호 흐름을 갱신한다. wide = 줄이 본문 오른쪽 끝까지 참."""
        t = text.strip()
        if not t or wide or len(t) > self.max_chars or self.is_leader(t) or t.endswith(("다.", "다")) \
                or re.search(r"\s[:：]\s", t):
            return None
        if self.bare(t) in self.unnumbered:
            self.path, self.label = [], self.bare(t)
            return 1, None, t
        m = self.ROMAN_RE.fullmatch(t)
        if m:
            r = ROMAN.index(m.group(1)) + 1
            if self.roman < r <= self.roman + 2:
                self.roman, self.path = r, []
                return 0, [r], t
            return None
        m = self.NUM_RE.fullmatch(t)
        if m:
            nums = [int(x) for x in m.group(1).split(".")]
            # 위 간격 조건은 숫자 하나 번호 ("3.")에만: 본문 목록 "1. … 2. …"과 헷갈리는 것은 그쪽뿐이고,
            # "1.2"·"3.2" 같은 여러 단계 번호는 번호 흐름만 맞으면 제목 (줄 간격이 고른 문서에서도 잡히게)
            if (gap_ok or len(nums) >= 2) and self._next_ok(nums):
                self.path = nums
                return len(nums), nums, t
        return None


def item_number(pattern: str, text: str) -> int | None:
    s = text.lstrip()
    if pattern == "circled" and s and "①" <= s[0] <= "⑳":
        return ord(s[0]) - ord("①") + 1
    if pattern in ("num_dot", "num_paren"):
        m = re.match(r"(\d+)", s)
        return int(m.group(1)) if m else None
    if pattern in ("hangul_dot", "hangul_paren") and s and s[0] in HANGUL_ORDER:
        return HANGUL_ORDER.index(s[0]) + 1
    if pattern == "paren_num":
        m = re.match(r"\((\d+)\)", s)
        return int(m.group(1)) if m else None
    if pattern == "paren_hangul" and len(s) > 1 and s[1] in HANGUL_ORDER:
        return HANGUL_ORDER.index(s[1]) + 1
    return None


def marker_key(pattern: str, text: str) -> str:
    """번호 패턴 키. 글머리표는 모양마다 다른 목록 (□와 ○는 다른 단계)."""
    return f"bullet:{text.lstrip()[:1]}" if pattern == "bullet" else pattern


class Tree:
    def __init__(self, join: str):
        self.nodes: list[dict] = []
        self.stack: list[dict] = []
        self.join = join
        self.prev_kind: str | None = None  # 바로 앞 항목 종류 (제목 이어짐, 띠 이어짐 판단)
        self.prev_line: dict | None = None
        self.byid: dict[str, dict] = {}
        self.last_item: dict[tuple, dict] = {}
        self.ref_nodes: dict[int, dict] = {}  # 보고서 모드: 각주 번호 → 본문에서 그 번호가 나온 노드
        self.ref_tables: dict[int, str] = {}  # 각주 번호 → 그 번호가 칸에 나온 표 (각주는 표가 붙은 노드에)

    def new(self, typ: str, parent: dict | None, d: dict | None, **kw) -> dict:
        n = {"id": f"N{len(self.nodes):05d}", "type": typ, "parent_id": parent["id"] if parent else None,
             "depth": (parent["depth"] + 1) if parent else 0, "title": None, "title_lines": [], "lines": [],
             "page_start": d["page"] if d else None, "page_end": d["page"] if d else None,
             "children": [], "tables": [], "boxes": [], "figures": [], **kw}
        if parent:
            parent["children"].append(n["id"])
        self.nodes.append(n)
        self.byid[n["id"]] = n
        if typ == "item":  # 같은 조 (또는 제목 노드) 안 번호 패턴별 마지막 항목 (닫힌 목록 이어 붙이기용)
            self.last_item[(self.boundary_id(), kw.get("marker"))] = n
        return n

    def boundary_id(self) -> str | None:
        """스택에서 가장 가까운 제목 노드 (조·관·편·절·계약·구역)의 id."""
        return next((s["id"] for s in reversed(self.stack) if s["type"] in LEVEL), None)

    def path_to(self, n: dict) -> list[dict]:
        out_ = []
        while n is not None:
            out_.append(n)
            n = self.byid.get(n["parent_id"])
        return out_[::-1]

    def pop_to(self, level: int) -> None:
        while self.stack and lvl(self.stack[-1]) >= level:
            self.stack.pop()

    def pop_leaves(self) -> None:
        while self.stack and self.stack[-1]["type"] in LEAVES:
            self.stack.pop()

    def add_line(self, n: dict, d: dict, as_title: bool = False) -> None:
        for k in d.get("footnote_refs", []):
            self.ref_nodes[k] = n
        (n["title_lines"] if as_title else n["lines"]).append({"page": d["page"], "line_id": d["line_id"], "text": d["text"].strip()})
        n["page_end"] = d["page"]
        n["page_start"] = n["page_start"] or d["page"]

    def close_to(self, d: dict) -> bool:
        """앞 줄과 세로 간격이 제목 이어짐 범위 안인가 (같은 쪽)."""
        q = self.prev_line
        if q is None or q["page"] != d["page"]:
            return False
        h = max(1.0, q["bottom"] - q["top"])
        return d["top"] - q["bottom"] <= P("tree.title_cont_gap_ratio") * h


def section_labels(lines: list[dict]) -> dict[tuple[int, int], dict]:
    """절 제목 줄마다 왼쪽 작은 상자 글자 (별표2, 별표 등)를 라벨로 짝짓는다. {(쪽, 제목 line_id): 라벨 줄}.
    라벨 = 같은 쪽, 상자 영역 (zone box) 줄, 글자 수 ≤ tree.section_label_max_chars, 제목 왼쪽 (x1 ≤ 제목 x0),
    세로로 같은 행 (중심 차 ≤ 제목 높이 × tree.section_label_row_ratio) 이거나 바로 위 (제목 top − 라벨 bottom ≤ 제목 높이).
    라벨 줄 자체는 트리 줄에서 빠지고 절 노드의 label·label_number·label_kind가 된다."""
    f_sec = font("section_title")
    heads = [d for d in lines if d["zone"] == "body" and d["font_key"] == f_sec and d["pattern"] == "none"]
    cands = [d for d in lines if d["zone"] == "box" and len(d["text"].strip()) <= P("tree.section_label_max_chars")]
    res, used = {}, set()
    for h in heads:
        hh = h["bottom"] - h["top"]
        cy = (h["top"] + h["bottom"]) / 2
        best = None
        for d in cands:
            if d["page"] != h["page"] or d["x1"] > h["x0"] or (d["page"], d["line_id"]) in used:
                continue
            same_row = abs((d["top"] + d["bottom"]) / 2 - cy) <= P("tree.section_label_row_ratio") * hh
            just_above = 0 <= h["top"] - d["bottom"] <= hh
            if same_row or just_above:
                dist = abs((d["top"] + d["bottom"]) / 2 - cy)
                if best is None or dist < best[0]:
                    best = (dist, d)
        if best:
            res[(h["page"], h["line_id"])] = best[1]
            used.add((best[1]["page"], best[1]["line_id"]))
    # 절 목록 줄 (별표 목록 쪽 등): 위에서 찾은 라벨 종류 (별표·유첨…)로 시작하는 남은 상자 라벨이 같은 행 본문 줄 왼쪽에 있으면
    # 그 본문 줄을 제목으로 하는 짧은 절 (stub). 인용이 이 절로 이어진다.
    kinds = {re.sub(r"[\s\d]", "", d["text"]) for d in res.values()} - {""}
    body = [d for d in lines if d["zone"] == "body" and (d["page"], d["line_id"]) not in res]
    for d in cands:
        if (d["page"], d["line_id"]) in used or re.sub(r"[\s\d]", "", d["text"]) not in kinds:
            continue
        cy, hh = (d["top"] + d["bottom"]) / 2, d["bottom"] - d["top"]
        row = [b for b in body if b["page"] == d["page"] and b["x0"] >= d["x1"]
               and abs((b["top"] + b["bottom"]) / 2 - cy) <= P("tree.section_label_row_ratio") * hh]
        if row:
            h = min(row, key=lambda b: b["x0"])
            res[(h["page"], h["line_id"])] = {**d, "stub": True}
            used.add((d["page"], d["line_id"]))
    return res


def wrapped(T: Tree, d: dict) -> bool:
    """바로 앞 줄이 같은 쪽의 이어지는 글 (표·박스·제목이 끼지 않음)이고 문장 끝 기호 (tree.sentence_end_chars)로 끝나지
    않음 → 이 줄은 줄바꿈된 문장 조각일 수 있다 (예: "…합니" 다음 줄 "다. …")."""
    q = T.prev_line
    return (q is not None and q["page"] == d["page"] and T.prev_kind in ("text", "item", "note", "bold", "para")
            and not q["text"].rstrip().endswith(tuple(P("tree.sentence_end_chars"))))


def place_item(T: Tree, d: dict, mk: str, num: int | None) -> tuple[str, int | None]:
    """번호 줄을 어디에 둘지: ("sibling", 스택 위치) / ("child", None) / ("text", None = 줄바꿈 조각).
    후보 = 현재 조 (또는 그 위 제목 노드) 안 스택의 같은 번호 패턴 노드 (주석 안 목록 포함). 순서:
    1) 번호가 바로 이어지고 x0가 tree.item_align_tol_pt 안인 후보의 형제
    2) 줄바꿈 조각이 아니면, 번호가 바로 이어지고 x0가 tree.item_consecutive_tol_pt 안인 후보의 형제
    3) 글머리표 (번호 없음): x0가 맞는 후보의 형제, 없으면 새 목록
    2-1) 번호가 같은 조 안 닫힌 목록 (스택에 없음)의 마지막 항목에 바로 이어지고 x0가 맞으면 그 목록에 다시 붙임
         (예: ①②③ ■제목 ④…: 글머리표 제목이 끼어도 원문자 번호가 조 단위로 이어짐)
    4) 번호 1: 새 목록 (현재 노드의 자식)
    5) x0가 맞는 후보의 형제 (번호 건너뜀, 검사에 걸림)
    6) 줄바꿈 조각이면 글, 아니면 중간 번호부터 시작하는 새 목록 (앞 번호가 표·박스 안 등)"""
    tol, wide = P("tree.item_align_tol_pt"), P("tree.item_consecutive_tol_pt")
    cands = []
    for k in range(len(T.stack) - 1, -1, -1):
        s = T.stack[k]
        if s["type"] in LEVEL:
            break
        if s.get("marker") == mk:
            cands.append(k)

    def dx(k):
        return abs(T.stack[k]["x0"] - d["x0"])

    def consec(k):
        n0 = T.stack[k].get("number")
        return num is not None and n0 is not None and num == n0 + 1

    for k in cands:
        if consec(k) and dx(k) <= tol:
            return "sibling", k
    if not wrapped(T, d):
        for k in cands:
            if consec(k) and dx(k) <= wide:
                return "sibling", k
    last = T.last_item.get((T.boundary_id(), mk))
    if (num is not None and num > 1 and last is not None and not any(s is last for s in T.stack) and last.get("number") == num - 1
            and abs(last["x0"] - d["x0"]) <= tol and any(s["id"] == last["parent_id"] for s in T.stack)):
        # 번호가 닫힌 목록에 이어짐 (사이에 글머리표 제목 등): 그 목록에 다시 붙인다. 목록의 부모가 아직 열려 있을 때만
        # (▶ 안내 줄마다 그 아래 ①②가 있고 번호가 조 단위로 이어지는 경우, 다음 ▶ 아래 ③을 앞 ▶ 목록으로 끌고 가지 않게)
        return "reattach", None
    if num is None:
        return next((("sibling", k) for k in cands if dx(k) <= tol), ("child", None))
    if num == 1:
        return "child", None
    for k in cands:
        if dx(k) <= tol:
            return "sibling", k
    return ("text", None) if wrapped(T, d) else ("child", None)


def build(items: list[tuple], join: str, labels: dict | None = None, body_size: float = 0.0,
          right_edge: float = 0.0, page_chapter: dict | None = None, table_refs: dict | None = None) -> Tree:
    T = Tree(join)
    labels = labels or {}
    RH = ReportHeadings(page_chapter) if mode() == "report" else None
    gap_ratio = P("tree.report_heading_gap_ratio") if RH else 0.0
    zone_nodes: dict[str, dict] = {}
    cur_zone = None
    f_band, f_pyeon, f_gwan = set(fonts_of("title_band")), font("pyeon_title"), font("gwan_title")
    f_art, f_sec = font("article_title"), font("section_title")
    for kind, key, payload in items:
        page = key[0]
        z = zone_of(page)[0]
        if z != cur_zone:
            cur_zone = z
            zn = zone_nodes.get(z) or T.new("zone", None, None, zone=z, title=z)
            zone_nodes[z] = zn
            T.stack = [zn]
            T.prev_kind = None
        if kind in ("table", "box", "figure"):
            T.pop_leaves()
            host = T.stack[-1]
            if kind == "table":  # 표 칸에 나온 각주 번호: 각주는 이 표가 붙은 노드에
                for k in (table_refs or {}).get(payload, ()):
                    T.ref_nodes[k], T.ref_tables[k] = host, payload
            host[{"table": "tables", "box": "boxes", "figure": "figures"}[kind]].append(payload)
            # 읽기 순서 복원용: 이 표·박스가 몇 번째 자식 뒤에 왔는지
            host.setdefault("attach_order", []).append({"kind": kind, "id": payload, "after_children": len(host["children"])})
            T.prev_kind, T.prev_line = kind, None
            continue
        if kind == "band":
            lines = payload
            if T.prev_kind == "band":
                c = T.stack[-1]
            else:
                T.pop_to(LEVEL["contract"])
                c = T.new("contract", T.stack[-1], lines[0])
                T.stack.append(c)
            for d in lines:
                T.add_line(c, d, as_title=True)
            T.prev_kind, T.prev_line = "band", None
            continue
        d = payload
        f, pat = d["font_key"], d["pattern"]
        cont = T.close_to(d)
        if RH is not None:
            if RH.is_leader(d["text"]):  # 목차 점선 줄
                continue
            if not re.search(r"[0-9A-Za-z가-힣]", d["text"]):  # 기호만 있는 줄 (도식 화살표 ⇨ 등)
                continue
            if d["page"] != RH.page:  # 쪽 첫 줄: 머리글 장 이름이 새 번호 없는 제목이면 그 제목부터
                RH.page = d["page"]
                lab = RH.page_label(d["page"])
                if lab:
                    T.pop_to(3)
                    n = T.new("heading", T.stack[-1], d, level=1, number=None, from_header=True)
                    n["title_lines"].append({"page": d["page"], "line_id": None, "text": lab})
                    T.stack.append(n)
                    T.prev_kind, T.prev_line = "heading", None
            if RH.is_label_line(d["text"]):  # 머리글로 이미 만든 제목과 같은 줄
                continue
            small = bool(body_size) and d["size"] < body_size - 0.5
            if T.stack[-1].get("marker") == "footnote" and not small:
                T.stack.pop()  # 각주 다음 본문 크기 줄: 각주를 닫는다
            q = T.prev_line
            h = max(1.0, d["bottom"] - d["top"])
            gap_ok = (q is None or q["page"] != d["page"] or T.prev_kind == "heading"
                      or d["top"] - q["bottom"] >= gap_ratio * h)
            wide = bool(right_edge) and d["x1"] >= right_edge - P("tree.report_wide_line_tol_pt")
            hd = None if small else RH.match(d["text"], gap_ok, wide)
            if hd is not None:
                level, nums, _ = hd
                T.pop_to(2 + level)
                n = T.new("heading", T.stack[-1], d, level=level, number=nums)
                T.add_line(n, d, as_title=True)
                T.stack.append(n)
                T.prev_kind, T.prev_line = "heading", d
                continue
            nums = None if (small or hd is not None) else RH.para_number(d["text"])
            if nums:  # 번호 문단 (3.1 조사결과 아래 3.1.1 …): 가장 가까운 제목 아래 항목
                while T.stack[-1]["type"] not in LEVEL:
                    T.stack.pop()
                n = T.new("item", T.stack[-1], d, marker="decimal", number=nums[-1], x0=d["x0"])
                T.add_line(n, d)
                T.stack.append(n)
                T.prev_kind, T.prev_line = "item", d
                continue
            cap = None if hd is not None else caption_kind(d["text"])
            if cap:  # 그림·표 설명 줄: 가장 가까운 제목 아래 설명 노드 (앞 항목 끝에 붙지 않게)
                while T.stack[-1]["type"] not in LEVEL:
                    T.stack.pop()
                n = T.new("caption", T.stack[-1], d, kind=cap[0], number=cap[1])
                T.add_line(n, d)
                T.prev_kind, T.prev_line = "caption", d
                continue
            if small and pat in ("num_paren", "paren_num"):
                T.pop_leaves()
                m = re.match(r"\s*\(?(\d+)", d["text"])
                num = int(m.group(1)) if m else None
                # 각주는 본문에서 그 번호 (위첨자)가 나온 노드에, 못 찾으면 지금 노드에
                host = T.ref_nodes.get(num, T.stack[-1]) if num is not None else T.stack[-1]
                n = T.new("note", host, d, marker="footnote", number=num, x0=d["x0"])
                n["attached_by"] = "ref" if num in T.ref_nodes else "position"
                if num in T.ref_tables and T.ref_nodes.get(num) is host:
                    n["ref_table"] = T.ref_tables[num]
                T.add_line(n, d)
                T.stack.append(n)
                T.prev_kind, T.prev_line = "note", d
                continue
        if f == f_pyeon and pat == "pyeon":
            T.pop_to(LEVEL["pyeon"])
            n = T.new("pyeon", T.stack[-1], d, number=int(re.search(r"(\d+)", d["text"]).group(1)))
            T.add_line(n, d, as_title=True)
            T.stack.append(n)
            T.prev_kind = "pyeon"
        elif f == f_gwan and pat == "gwan":
            T.pop_to(LEVEL["gwan"])
            n = T.new("gwan", T.stack[-1], d, number=int(re.search(r"(\d+)", d["text"]).group(1)))
            T.add_line(n, d, as_title=True)
            T.stack.append(n)
            T.prev_kind = "gwan"
        elif f == f_art and pat in ("art_n", "art_nm") and ART_RE.match(d["text"]):
            m = ART_RE.match(d["text"])
            T.pop_to(LEVEL["article"])
            n = T.new("article", T.stack[-1], d, number=[int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or m.group(4) or 0)],
                       branch_without_ui=m.group(4) is not None)
            T.add_line(n, d, as_title=True)
            T.stack.append(n)
            T.prev_kind = "article"
        elif (f == f_sec and pat == "none") or (labels.get((d["page"], d["line_id"])) or {}).get("stub"):
            if T.prev_kind == "section" and cont and not (labels.get((d["page"], d["line_id"])) or {}).get("stub")                     and (d["page"], d["line_id"]) not in labels:
                T.add_line(T.stack[-1], d, as_title=True)
            else:
                T.pop_to(LEVEL["section"])
                lab = labels.get((d["page"], d["line_id"]))
                lab_text = lab["text"].strip() if lab else None
                num = re.search(r"(\d+)", lab_text) if lab_text else None
                n = T.new("section", T.stack[-1], d, label=lab_text, label_number=int(num.group(1)) if num else None,
                          stub=bool(lab and lab.get("stub")),
                          label_kind=(re.sub(r"[\s\d]", "", lab_text) or None) if lab_text else None)
                T.add_line(n, d, as_title=True)
                T.stack.append(n)
            T.prev_kind = "section"
        elif pat == "none" and T.prev_kind in ("article", "pyeon", "gwan") and cont and f == T.prev_line["font_key"]:
            T.add_line(T.stack[-1], d, as_title=True)  # 제목 둘째 줄
        elif pat in ITEM_PATTERNS and (pl := place_item(T, d, marker_key(pat, d["text"]), item_number(pat, d["text"])))[0] != "text":
            if pl[0] == "sibling":
                del T.stack[pl[1]:]
            elif pl[0] == "reattach":
                last = T.last_item[(T.boundary_id(), marker_key(pat, d["text"]))]
                T.stack = T.path_to(T.byid[last["parent_id"]])
            else:  # 새 목록: 굵은 줄·문단은 닫고, 주석은 안쪽 목록을 가질 수 있다 (주석보다 왼쪽에서 시작하면 주석을 닫음)
                while T.stack[-1]["type"] in ("bold", "para") or (
                        T.stack[-1]["type"] == "note" and d["x0"] < T.stack[-1]["x0"] - P("tree.item_align_tol_pt")):
                    T.stack.pop()
            n = T.new("item", T.stack[-1], d, marker=marker_key(pat, d["text"]), number=item_number(pat, d["text"]), x0=d["x0"])
            T.add_line(n, d)
            T.stack.append(n)
            T.prev_kind = "item"
        elif pat in NOTE_PATTERNS:
            T.pop_leaves()
            n = T.new("note", T.stack[-1], d, marker=pat, x0=d["x0"])
            T.stack.append(n)
            rest = NOTE_RE[pat].sub("", d["text"].lstrip(), count=1)
            rp = line_pattern(rest)
            if rp in ITEM_PATTERNS and item_number(rp, rest) == 1:
                # "㈜ 1. …": 주석 줄 안에서 목록이 시작 → 주석 아래 1번 항목 (다음 "2."가 이 목록에 이어진다)
                c = T.new("item", n, d, marker=marker_key(rp, rest), number=1, x0=d["x0"])
                T.add_line(c, d)
                T.stack.append(c)
            else:
                T.add_line(n, d)
            T.prev_kind = "note"
        elif f == f_art and pat == "none":
            T.pop_leaves()
            n = T.new("bold", T.stack[-1], d)
            T.add_line(n, d)
            T.stack.append(n)
            T.prev_kind = "bold"
        else:
            top = T.stack[-1]
            if top["type"] == "bold" and d["bold_ratio"] <= 0.5:
                T.stack.pop()
                top = T.new("para", T.stack[-1], d)
                T.stack.append(top)
            T.add_line(top, d)
            T.prev_kind = "text"
        T.prev_line = d
    return T


def page_chapters(lines: list[dict]) -> dict[int, str]:
    """쪽마다 머리글 장 이름: 머리글 줄 (excluded_reason header)에서 머리글끼리 같은 끝 부분 (문서 제목)을 뺀 글자 (공백 없음)."""
    heads = {}
    for d in lines:
        if d.get("excluded_reason") == "header":
            heads.setdefault(d["page"], re.sub(r"\s", "", d["text"]))
    if len(heads) < 3:
        return {}
    suffix = os.path.commonprefix([h[::-1] for h in heads.values()])[::-1]
    if len(suffix) < 5:
        return {}
    return {p: h[: len(h) - len(suffix)] for p, h in heads.items() if len(h) > len(suffix)}


def make_figures(usable: list[dict], table_note_ids: set) -> tuple[list[dict], set]:
    """제외한 예시 상자 (excluded_regions.csv의 example_box)를 그림 자리로 남긴다: 쪽 그림을 잘라 secure/figures/<id>.png로 두고,
    바로 아래 주석 (※·(주)·㈜, 표 아래 주석과 같은 규칙 tables_extract.notes_below)을 그림에 붙인다.
    예시를 빼면 그 아래 주석이 홀로 떠 있던 문제 (예시 그림의 용어 설명 주석)를 막는다. (그림 목록, 그림 주석 줄 id)"""
    import csv

    from PIL import Image

    from evalcore import pages_meta
    from tables_extract import notes_below

    by_page = defaultdict(list)
    for d in usable:
        by_page[d["page"]].append(d)
    rows = [r for r in csv.DictReader(open(RESULTS / "parsing" / "excluded_regions.csv", encoding="utf-8"))
            if r["reason"] == "example_box" and int(r["page"]) in set(INCLUDED_PAGES)]
    rows.sort(key=lambda r: (int(r["page"]), float(r["top"])))
    figs, used, n_by_page = [], set(table_note_ids), Counter()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for r in rows:
        p = int(r["page"])
        bbox = [float(r[k]) for k in ("x0", "top", "x1", "bottom")]
        notes, ids = notes_below({"bbox": bbox}, [d for d in by_page[p] if (p, d["line_id"]) not in used], set())
        used |= {(p, i) for i in ids}
        fid = f"F{p:03d}_{n_by_page[p]}"
        n_by_page[p] += 1
        img = Image.open(SECURE / "renders" / f"p{p:03d}.png")
        sc = img.width / pages_meta()[p]["width"]
        img.crop(tuple(int(v * sc) for v in (bbox[0] - 2, bbox[1] - 2, bbox[2] + 2, bbox[3] + 2))).save(
            secure_path(FIG_DIR / f"{fid}.png"))
        figs.append({"id": fid, "kind": "example", "page": p, "bbox": bbox, "source": r["source"],
                     "image": (FIG_DIR / f"{fid}.png").relative_to(OUT_DIR).as_posix(),  # 결과 폴더 기준
                     "notes": notes, "note_line_ids": ids})
    with open(secure_path(FIG_DIR / "figures.jsonl"), "w", encoding="utf-8") as f:
        for x in figs:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    return figs, used - set(table_note_ids)


def main() -> int:
    setup("tree")
    join = load_week1()[0].cell_line_join
    inc = set(INCLUDED_PAGES)
    lines = [d for d in map(json.loads, (SECURE / "lines" / "lines_marked.jsonl").open(encoding="utf-8"))
             if d["page"] in inc and not d["is_page_number"]]
    for d in lines:  # 덤프 뒤에 추가한 패턴 ((가), 글머리표)을 반영해 줄 패턴을 다시 계산
        d["pattern"] = line_pattern(d["text"])
    usable = [d for d in lines if not d["excluded"]]
    regs = [json.loads(s) for s in (SECURE / "tables" / "table_regions.jsonl").read_text(encoding="utf-8").splitlines()]
    band_rids = {r["source"] for r in regs if r["decided"] == "title_band"}
    tid_src = {r["table_id"]: r["source"] for r in regs if r.get("table_id")}
    tables = [json.loads(s) for s in (SECURE / "tables" / "tables.jsonl").read_text(encoding="utf-8").splitlines()]
    blocks = [json.loads(s) for s in (SECURE / "boxes" / "box_blocks.jsonl").read_text(encoding="utf-8").splitlines()]

    used_regions = {tid_src[i] for t in tables for i in [t["table_id"]] + t.get("merged_ids", [])}
    used_regions |= {rid for b in blocks for rid in b["region_ids"]}
    note_ids = set()
    for t in tables:  # 표 아래 주석 줄 (이어 붙인 표는 마지막 쪽)과 표 설명 줄 (표에 붙음)
        note_ids |= {(t["pages"][-1], i) for i in t["note_line_ids"]}
        if t.get("caption"):
            note_ids.add((t["caption"]["page"], t["caption"]["line_id"]))
    figures, fig_note_ids = make_figures(usable, note_ids)
    labels = section_labels([d for d in usable if d["region_id"] not in used_regions])
    label_ids = {(d["page"], d["line_id"]) for d in labels.values()}
    items, acc = [], Counter()
    band_lines = defaultdict(list)
    for d in usable:
        if (d["page"], d["line_id"]) in label_ids:
            acc["section_label"] += 1
        elif (d["page"], d["line_id"]) in fig_note_ids:
            acc["figure_note"] += 1
        elif d["region_id"] in band_rids:
            band_lines[d["region_id"]].append(d)
            acc["band"] += 1
        elif d["region_id"] in used_regions and d["zone"] != "note":
            # 1주차 표 파서는 표 아래 글을 표의 주석 범위 (zone note, 같은 region_id)로 묶는다. 그중 주석 패턴 줄만
            # 표 주석 (note_line_ids)으로 들어가므로, 나머지 note 줄은 아래에서 트리 줄로 보낸다
            acc["in_table_or_box"] += 1
        elif (d["page"], d["line_id"]) in note_ids:
            acc["table_note"] += 1
        else:
            items.append(("line", (d["page"], d["top"], d["x0"]), d))
            acc["tree"] += 1
    for rid, ls in band_lines.items():
        ls.sort(key=lambda d: (d["top"], d["x0"]))
        items.append(("band", (ls[0]["page"], ls[0]["top"], ls[0]["x0"]), ls))
    for t in tables:
        items.append(("table", (t["page"], t["bbox"][1], t["bbox"][0]), t["table_id"]))
    for b in blocks:
        items.append(("box", (b["page"], b["bboxes"][0][1], b["bboxes"][0][0]), b["block_id"]))
    for f in figures:
        items.append(("figure", (f["page"], f["bbox"][1], f["bbox"][0]), f["id"]))
    items.sort(key=lambda x: x[1])
    bsize = float(font("body").rsplit("/", 1)[1])
    if not bsize and usable:  # 본문 폰트를 모름: 줄 크기 최빈값
        bsize = float(Counter(round(d["size"]) for d in usable).most_common(1)[0][0])
    xs = sorted(d["x1"] for d in usable if d["zone"] == "body")
    right = xs[int(0.95 * (len(xs) - 1))] if xs else 0.0  # 본문 오른쪽 끝 (x1 95번째 백분위)
    # 표 칸 줄의 위첨자 각주 번호 (덤프 footnote_refs) → 표 id (이어 붙인 표는 첫 표 id)
    main_tid = {i: t["table_id"] for t in tables for i in [t["table_id"]] + t.get("merged_ids", [])}
    src_tid = {src: main_tid[tid] for tid, src in tid_src.items() if tid in main_tid}
    table_refs: dict = defaultdict(set)
    for d in usable:
        if d.get("footnote_refs") and d["region_id"] in src_tid:
            table_refs[src_tid[d["region_id"]]] |= set(d["footnote_refs"])
    T = build(items, join, labels, bsize, right, page_chapters(lines) if mode() == "report" else None, table_refs)
    nodes = T.nodes
    byid = {n["id"]: n for n in nodes}

    def ancestor(n, typ):
        while n is not None and n["type"] != typ:
            n = byid.get(n["parent_id"])
        return n

    vocab = Vocab(d["text"] for d in usable) if profile().get("smart_line_join") else None
    for n in nodes:  # 줄 잇기: 보고서 프로필 smart_line_join이면 단어 중간 줄바꿈은 붙여서 (parsing/textjoin.py)
        n["title"] = n["title"] if n["type"] == "zone" else (join_lines([x["text"] for x in n["title_lines"]], vocab, join) or None)
        n["text"] = join_lines([x["text"] for x in n["lines"]], vocab, join)
        a = ancestor(n, "article")
        n["article_id"] = a["id"] if a else None
        c = ancestor(n, "contract")
        n["contract_id"] = c["id"] if c else None
        hd = ancestor(n, "heading")
        n["heading_id"] = hd["id"] if hd else None
        path, q = [], n
        while q is not None:
            path.append(q["id"])
            q = byid.get(q["parent_id"])
        n["path"] = path[::-1]
    for n in nodes:
        n["heading_path"] = [byid[i]["title"] for i in n["path"] if byid[i]["type"] == "heading"]

    link_citations(nodes, byid)
    att = []
    for n in nodes:
        for kind in ("tables", "boxes", "figures"):
            for x in n[kind]:
                att.append({"kind": {"tables": "table", "boxes": "box", "figures": "figure"}[kind], "id": x, "node_id": n["id"],
                            "node_type": n["type"], "article_id": n["article_id"], "contract_id": n["contract_id"],
                            "heading_id": n["heading_id"]})
    TREE_DIR.mkdir(parents=True, exist_ok=True)
    with open(secure_path(TREE_DIR / "nodes.jsonl"), "w", encoding="utf-8") as f:
        for n in nodes:
            f.write(json.dumps(n, ensure_ascii=False) + "\n")
    with open(secure_path(TREE_DIR / "attachments.jsonl"), "w", encoding="utf-8") as f:
        for a in att:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    # 조·항 참조 + 별표·유첨 인용 (청킹 refs_out 입력). 노드 파일과 기존 cites는 그대로 둔다
    refs = extract_refs(nodes, byid, tables, blocks, figures, att)
    with open(secure_path(TREE_DIR / "refs.jsonl"), "w", encoding="utf-8") as f:
        for r in refs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    out("refs", n=len(refs), kinds=dict(Counter(r["kind"] for r in refs)), scopes=dict(Counter(r["scope"] for r in refs)),
        resolved=sum(r["resolved"] for r in refs), reasons=dict(Counter(r["reason"] for r in refs if r["reason"])),
        title_given=sum(r["title_given"] for r in refs), title_mismatch=sum(r["title_match"] is False for r in refs))
    # 용어집 소속 조항: 박스 블록이 붙은 노드의 조
    box_at = {a["id"]: a for a in att if a["kind"] == "box"}
    gpath = SECURE / "boxes" / "glossary.jsonl"
    gl = [json.loads(s) for s in gpath.read_text(encoding="utf-8").splitlines()]
    for g in gl:
        a = box_at.get(g["block_id"])
        art = byid.get(a["article_id"]) if a and a["article_id"] else None
        con = byid.get(a["contract_id"]) if a and a["contract_id"] else None
        g["parent_node"] = a["node_id"] if a else None
        g["parent_article"] = {"node_id": art["id"], "title": art["title"]} if art else None
        g["contract"] = {"node_id": con["id"], "title": con["title"]} if con else None
    with open(secure_path(gpath), "w", encoding="utf-8") as f:
        for g in gl:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    from review.tree import check_tree  # 번호 흐름 검사 (수치만 화면에)
    checks = check_tree(nodes, byid)
    total_lines = sum(len(n["lines"]) + len(n["title_lines"]) for n in nodes if n["type"] != "contract")
    acc["tree_lines_in_nodes"] = total_lines
    n_spots = 0
    if review_mode():
        from review.tree import write_report, write_spot_check, write_structure, write_user_check
        write_report(nodes, att, acc, checks, len(usable), gl)
        write_structure(nodes, checks)
        write_user_check(nodes, byid, checks, gl)
        n_spots = write_spot_check(nodes, byid, checks, {(d["page"], d["line_id"]): d for d in usable})
    out("done", nodes=len(nodes), types=dict(Counter(n["type"] for n in nodes)), lines=dict(acc), usable=len(usable),
        attachments=dict(Counter(a["node_type"] for a in att)), no_article=sum(a["article_id"] is None for a in att),
        checks={k: len(v) for k, v in checks.items()}, spots=n_spots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
