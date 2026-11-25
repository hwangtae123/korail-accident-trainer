"""2차 2단계 2-2~2-5: 표 추출 (모양별), 위쪽 연결 정보, 출력, 자동 검증.

입력: secure/tables/table_regions.jsonl (tables_classify.py), secure/lines/by_page/ (pdf_lines.py), lines_marked.jsonl (제외 표시).
모양별 추출:
  (a) 1week-rag parse_table (pdfplumber 선 기준 격자·병합 칸). 칸 글자는 1week 규칙 (cell_line_join).
      폭·높이가 sliver_max_pt 미만이고 모든 칸이 빈 열·행 (이중 테두리 틈새)은 지운다.
  (b)·(c) 줄 정렬 기준: 열 = 표 좌우 끝 + 안쪽 세로선 (tables_classify의 v_in_x), 글자는 중심 x로 열에 넣는다.
      머리 행 = 위에 글자 줄이 있는 첫 안쪽 가로선 (표 위·아래 끝 제외) 위의 줄. 본문 행: 첫 열이 행 시작 표시 (ROW_MARKERS)로 시작하는
      줄이 본문 줄의 절반 이상이면 표시 기준 (표시 없는 줄은 앞 행에 이어 붙임), 아니면 줄마다 한 행 (첫 열이 빈 줄은 앞 행에 붙임).
  (d) 라벨 열 + 내용 열: 행 = 표 안 가로선 사이 구간 (가로선 없이 한 구간에 라벨 줄이 label_rows_min개 이상이고 모두 같은 높이에 내용 줄이 있으면 줄마다 한 행), 라벨 = 라벨 열 글자 줄 묶음 (세로 간격 ≤ label_gap_pt) 중 구간과
      가장 많이 겹치는 것. 행 = [라벨, 내용].
공통: 쪽 넘김 = 다음 포함 쪽의 첫 표가 쪽 맨 위에 있고 (위에 본문 줄 없음) 같은 모양·같은 열 위치 (± col_match_tol_pt)이고
      머리 행이 없으면, 앞 쪽 마지막 표 (아래에 본문 줄 없음)에 이어 붙인다.
      표 바로 아래 (주)·※·㈜ 블록 = 표 아래 note_gap_pt 안에서 주석 표시로 시작하는 줄과 그 뒤 이어지는 줄.
위쪽 연결 (2-3): 표 제목 = 표 위 title_gap_pt 안의 가장 가까운 줄이 굵거나 제목 폰트, 도입 줄 = 그 밖의 바로 위 줄,
      앞 번호 줄 = 표 앞 (같은 쪽 위, 없으면 앞 포함 쪽)에서 가장 가까운 번호 줄 (조·항·호·목 표시).
확신도: low = 격자 검사 실패 (a), 빈 칸 비율 높음, 숫자 열에 숫자 아닌 칸, 이미지 칸 (c), 행이 없음.

출력: secure/tables/tables.jsonl (원문 포함)
확인용 출력 (--review, parsing/review/tables_extract.py): results/parsing/tables_report.md (집계만),
      review/wireframe/extract_<table_id>.png + review/tables_extract_examples.md (구조만),
      secure/review/tables_check.md (사람 확인용: 장해분류표 표와 지급사유·지급금액 표의 추출 결과와 쪽)
실행 (requirements.txt 환경): python parsing/tables_extract.py
"""

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import P, caption_kind, font, fonts_of, profile  # noqa: E402
from textjoin import Vocab, join_lines  # noqa: E402
from evalcore import chars_of, lines_of, page_geometry, page_objects  # noqa: E402
from pdf_lines import line_pattern, load_week1  # noqa: E402
from safeio import SECURE, out, review_mode, secure_path, setup  # noqa: E402
from samples import INCLUDED_PAGES  # noqa: E402

ROW_MARKERS = ("num_paren", "hangul_paren", "num_dot", "hangul_dot", "circled", "paren_num")
NOTE_PATTERNS = ("note_ju", "note_ref", "note_cju")
NUMBERED = ("art_n", "art_nm", "circled", "num_dot", "hangul_dot", "num_paren", "hangul_paren", "paren_num")
# 숫자 칸: 숫자·쉼표·점 (+ 부호, 범위 "65~23"·"1,350~1,356")
NUM_RE = re.compile(r"^[+\-±]?[\d,.\s]+(?:[~∼～\-]\s*[\d,.\s]+)?%?$")
LINE_SEP = "\ue0ff"  # 보고서 프로필 smart_line_join: 칸 안 줄 사이 표시 (tidy_rows에서 textjoin으로 잇는다)
ROW_START_RE = re.compile(r"^\s*(?:[•·○●◦\-–※□■▶▷◆◇①-⑳]|\d+[.)]|\(\d+\)|[가나다라마바사아자차카타파하][.)])")
TABLE_DIR = SECURE / "tables"
# 확인 그림에 쓰는 쪽별 칸 좌표
DRAW_KEYS = ("grid_xs", "grid_ys", "cells", "col_x", "row_y", "label_spans", "header_y")


def load_marked() -> dict[tuple[int, int], str | None]:
    res = {}
    with open(SECURE / "lines" / "lines_marked.jsonl", encoding="utf-8") as f:
        for s in f:
            d = json.loads(s)
            res[(d["page"], d["line_id"])] = d["excluded_reason"]
    return res


def split_cols(chars: list[dict], bounds: list[float]) -> list[str]:
    cols = [[] for _ in range(len(bounds) - 1)]
    for c in sorted(chars, key=lambda c: c["x0"]):
        cx = (c["x0"] + c["x1"]) / 2
        i = next((k for k in range(len(bounds) - 1) if cx < bounds[k + 1]), len(bounds) - 2)
        cols[i].append(c["text"])
    return ["".join(c).strip() for c in cols]


def join(a: str, b: str, sep: str) -> str:
    return b if not a else (a if not b else a + sep + b)


def table_lines(t: dict) -> tuple[list[dict], dict[int, list[dict]]]:
    p = t["page"]
    ls = [d for d in lines_of(p) if d["region_id"] == t["source"] and d["zone"] in ("table", "box")]
    by_line: dict[int, list[dict]] = defaultdict(list)
    for c in chars_of(p, with_space=True):
        if c["region_id"] == t["source"] and c["zone"] in ("table", "box"):
            by_line[c["line_id"]].append(c)
    return sorted(ls, key=lambda d: (d["top"], d["x0"])), by_line


def extract_cols(t: dict, line_join: str) -> dict:
    x0, top, x1, bottom = t["bbox"]
    bounds = [x0 - 1] + list(t.get("v_in_x", [])) + [x1 + 1]
    inner_h = [y for y in t.get("h_y", []) if top + 2 < y < bottom - 2]
    ls, by_line = table_lines(t)
    # 머리 행 경계 = 위에 글자 줄이 하나 이상 있는 첫 안쪽 가로선 (머리 칸 테두리가 겹쳐 있어 맨 위 선들은 건너뜀)
    header_y = next((y for y in inner_h if any(d["bottom"] <= y + 1 for d in ls)), None) if t["shape"] == "b" else None
    header, body = [], []
    for d in ls:
        cells = split_cols(by_line.get(d["line_id"], []), bounds)
        (header if header_y is not None and d["bottom"] <= header_y + 1 else body).append((d, cells))
    hdr = [[""] * (len(bounds) - 1)]
    for _, cells in header:
        hdr[0] = [join(a, b, " ") for a, b in zip(hdr[0], cells)]
    marker_mode = sum(line_pattern(c[0]) in ROW_MARKERS for _, c in body if c[0]) * 2 >= max(len(body), 1)
    rows: list[list[str]] = []
    row_y: list[float] = []  # 행마다 첫 줄 top (확인 그림용)
    for d, cells in body:
        start = (line_pattern(cells[0]) in ROW_MARKERS) if marker_mode else bool(cells[0])
        if rows and not start:
            rows[-1] = [join(a, b, line_join) for a, b in zip(rows[-1], cells)]
        else:
            rows.append(cells)
            row_y.append(round(d["top"] - 1, 1))
    return {"method": "line_align", "n_cols": len(bounds) - 1, "header": hdr if header else [], "rows": rows,
            "col_x": [round(b, 1) for b in bounds], "row_y": row_y,
            "header_y": round(header_y, 1) if header else None, "marker_mode": marker_mode}


def extract_d(t: dict, line_join: str) -> dict:
    x0, top, x1, bottom = t["bbox"]
    sep = t["sep_x"]
    ls, by_line = table_lines(t)
    label_lines, content_lines = [], []
    for d in ls:
        cs = by_line.get(d["line_id"], [])
        lab = "".join(c["text"] for c in sorted(cs, key=lambda c: c["x0"]) if (c["x0"] + c["x1"]) / 2 < sep).strip()
        con = "".join(c["text"] for c in sorted(cs, key=lambda c: c["x0"]) if (c["x0"] + c["x1"]) / 2 >= sep).strip()
        if lab:
            label_lines.append((d["top"], d["bottom"], lab))
        if con:
            content_lines.append((d["top"], d["bottom"], con))
    groups: list[list] = []
    for tp, bt, txt in label_lines:
        if groups and tp - groups[-1][1] <= P("table_extract.label_gap_pt"):
            groups[-1][1] = max(groups[-1][1], bt)
            groups[-1][2] = groups[-1][2] + txt
        else:
            groups.append([tp, bt, txt])
    cuts = [top] + [y for y in t.get("h_y", []) if top + 2 < y < bottom - 2] + [bottom]
    rows, row_y = [], []
    for a, b in zip(cuts, cuts[1:]):
        con = [txt for tp, bt, txt in content_lines if a - 1 <= (tp + bt) / 2 <= b + 1]
        if not con:
            continue
        # 행 사이 가로선이 없어 한 구간에 라벨 줄이 여럿 (label_rows_min 이상)이고 라벨 줄마다 같은 높이에 내용 줄이 있으면
        # 줄마다 한 행 (번호 열 + 이름 열 목록 표). 라벨 없는 내용 줄은 앞 행에 이어 붙인다
        labs = [(tp, bt, txt) for tp, bt, txt in label_lines if a - 1 <= (tp + bt) / 2 <= b + 1]
        same_y = lambda l, c: abs((l[0] + l[1]) / 2 - (c[0] + c[1]) / 2) < P("table_extract.label_row_align_pt")  # noqa: E731
        cin = [c for c in content_lines if a - 1 <= (c[0] + c[1]) / 2 <= b + 1]
        if len(labs) >= P("table_extract.label_rows_min") and all(any(same_y(l, c) for c in cin) for l in labs):
            for c in cin:
                l = next((l for l in labs if same_y(l, c)), None)
                if l is not None or not rows:
                    rows.append([l[2] if l else "", c[2]])
                    row_y.append(round(c[0] - 1, 1))
                else:
                    rows[-1][1] = line_join.join([rows[-1][1], c[2]])
            continue
        lab = max(groups, key=lambda g: min(g[1], b) - max(g[0], a), default=None)
        rows.append([lab[2] if lab and min(lab[1], b) - max(lab[0], a) > 0 else "", line_join.join(con)])
        row_y.append(round(a, 1))
    return {"method": "label_content", "n_cols": 2, "header": [], "rows": rows, "row_y": row_y,
            "label_spans": [[round(g[0], 1), round(g[1], 1)] for g in groups],
            "col_x": [round(x0, 1), round(sep, 1), round(x1, 1)]}


def _fill_key(o: dict) -> tuple:
    """채움 색 비교용 키. 흰색 (회색조 1, RGB 1,1,1, CMYK 0,0,0,0)은 쪽 바탕과 같게 본다."""
    c = o["non_stroking_color"] or [0.0]
    if all(v == 1.0 for v in c) and len(c) in (1, 3) or len(c) == 4 and not any(c):
        return ("W",)
    return tuple(round(v, 2) for v in c)


def invisible_segment_ids(geom, region, objs) -> tuple[list[int], int]:
    """region 안쪽 선분 중 눈에 보이지 않는 채움 사각형 테두리의 id와, 채움 테두리 선분 수.

    그린 선 (선 객체, 얇은 사각형, 테두리 있는 사각형)과 겹치는 선분은 보인다. 채움 사각형 테두리뿐인 선분은
    선 양옆 띠 (edge_strip_pt)를 여러 점에서 보고, 모든 점의 채움 색이 같으면 (같은 색이 틈 없이 이어지면) 보이지 않는다.
    칸 배경 사각형 사이 흰 틈이나 색이 다른 칸의 경계는 보이는 선이다.
    """
    tol, thin, margin = P("geometry.touch_tol_pt"), P("geometry.thin_object_max_pt"), P("geometry.inner_margin_pt")
    strip, n_y = P("table_extract.edge_strip_pt"), P("table_extract.edge_samples")
    x0, top, x1, bottom = region.bbox

    def edges(o, orient):
        return (o["x0"], o["x1"]) if orient == "v" else (o["top"], o["bottom"])

    def span(o, orient):
        return (o["top"], o["bottom"]) if orient == "v" else (o["x0"], o["x1"])

    drawn = list(objs.lines) + [o for o in objs.rects if o["stroke"] or min(o["x1"] - o["x0"], o["bottom"] - o["top"]) <= thin]
    fills = [o for o in objs.rects if o["fill"] and not o["stroke"] and min(o["x1"] - o["x0"], o["bottom"] - o["top"]) > thin]
    inv, n_fill = [], 0
    for i in region.segment_ids:
        s = geom.segments[i]
        lo, hi = (x0, x1) if s.orient == "v" else (top, bottom)
        if not (lo + margin < s.pos < hi - margin):
            continue

        def touches(o):
            a, b = span(o, s.orient)
            return a <= s.end and b >= s.start

        if any(touches(o) and (min(abs(e - s.pos) for e in edges(o, s.orient)) <= tol
                               or edges(o, s.orient)[0] - tol <= s.pos <= edges(o, s.orient)[1] + tol and o in objs.lines)
               for o in drawn):
            continue
        if not any(touches(o) and min(abs(e - s.pos) for e in edges(o, s.orient)) <= tol for o in fills):
            continue
        n_fill += 1
        near = [o for o in fills if touches(o) and edges(o, s.orient)[0] <= s.pos + strip and edges(o, s.orient)[1] >= s.pos - strip]
        keys = set()
        for k in range(1, n_y + 1):
            q = s.start + (s.end - s.start) * k / (n_y + 1)
            for d in (j * strip / 5 for j in range(-5, 6)):
                xy = (s.pos + d, q) if s.orient == "v" else (q, s.pos + d)
                hit = [o for o in near if o["x0"] <= xy[0] <= o["x1"] and o["top"] <= xy[1] <= o["bottom"]]
                keys.add(_fill_key(hit[-1]) if hit else ("W",))  # 나중에 그린 사각형이 위에 보인다
        if len(keys) == 1:
            inv.append(i)
    return inv, n_fill


def fix_region_lines(geom, region, objs, tol: float):
    """격자를 만들기 전 선분 보정. (geom, region, 보이지 않아 뺀 선분 수, 닫은 옆면 목록)을 돌려준다.

    1) 보이지 않는 채움 사각형 테두리 (같은 색 사각형을 안쪽에 겹쳐 그린 칸 등)는 칸 경계가 아니므로 뺀다.
    2) 옆 테두리가 없는 표 (가로선만 끝까지 가고 맨 바깥 세로선이 없음)에서 영역 글자가 맨 바깥 세로선 밖에 있으면
       영역 끝에 세로선을 넣어 그 열을 닫는다. 없으면 그 열 글자가 격자 밖으로 빠진다.
    """
    inv, _ = invisible_segment_ids(geom, region, objs)
    keep = [i for i in region.segment_ids if i not in set(inv)]
    vs = [geom.segments[i].pos for i in keep if geom.segments[i].orient == "v"]
    x0, top, x1, bottom = region.bbox
    inner = [c for c in geom.chars if c.text.strip() and x0 <= (c.x0 + c.x1) / 2 <= x1 and top <= (c.top + c.bottom) / 2 <= bottom]
    Seg = type(geom.segments[0])
    extra, closed = [], []
    if vs:
        if min(vs) > x0 + tol and any((c.x0 + c.x1) / 2 < min(vs) for c in inner):
            extra.append(Seg("v", x0, top, bottom))
            closed.append("left")
        if max(vs) < x1 - tol and any((c.x0 + c.x1) / 2 > max(vs) for c in inner):
            extra.append(Seg("v", x1, top, bottom))
            closed.append("right")
    if not inv and not extra:
        return geom, region, 0, []
    n = len(geom.segments)
    geom2 = replace(geom, segments=list(geom.segments) + extra)
    region2 = replace(region, segment_ids=sorted(keep + list(range(n, n + len(extra)))))
    return geom2, region2, len(inv), closed


def extract_a(t: dict, geom, objs, cfg, split_regions, parse_table) -> dict:
    tabs, boxes = split_regions(geom, cfg)
    # 영역 이름: p<쪽>#t<i> (표 후보) 또는 p<쪽>#b<j> (상자였는데 3단계 기하 판정으로 표가 된 것)
    kind, idx = t["source"].rsplit("#", 1)[1][0], int(t["source"].rsplit("#", 1)[1][1:])
    region = (tabs if kind == "t" else boxes)[idx]
    below = [r.bbox[1] for r in tabs if r.bbox[1] >= region.bbox[3] - cfg.snap_tol]
    geom, region, n_inv, closed = fix_region_lines(geom, region, objs, cfg.snap_tol)
    pt = parse_table(geom, region, cfg, min(below) if below else None)
    n_r, n_c = pt.grid.n_rows, pt.grid.n_cols
    grid = [[""] * n_c for _ in range(n_r)]
    for c in pt.cells:
        for r in range(c.row, min(c.row + c.rowspan, n_r)):
            for k in range(c.col, min(c.col + c.colspan, n_c)):
                grid[r][k] = c.text
    # 이중 테두리 틈새: 폭·높이가 sliver_max_pt 미만이고 모든 칸이 빈 열·행은 지운다
    xs, ys, sl = pt.grid.xs, pt.grid.ys, P("table_extract.sliver_max_pt")
    keep_c = [k for k in range(n_c) if not (xs[k + 1] - xs[k] < sl and all(not grid[r][k] for r in range(n_r)))]
    keep_r = [r for r in range(n_r) if not (ys[r + 1] - ys[r] < sl and all(not grid[r][k] for k in range(n_c)))]
    h = sum(1 for r in keep_r if r < pt.header_rows)
    grid = [[grid[r][k] for k in keep_c] for r in keep_r]
    col_x = [xs[k] for k in keep_c] + [xs[keep_c[-1] + 1]] if keep_c else list(xs)
    row_y = [ys[r] for r in keep_r] + [ys[keep_r[-1] + 1]] if keep_r else list(ys)
    return {"method": "grid", "n_cols": len(keep_c), "header": grid[:h], "rows": grid[h:],
            "cells": [{"r": c.row, "c": c.col, "rs": c.rowspan, "cs": c.colspan} for c in pt.cells],
            "dropped_slivers": [n_c - len(keep_c), n_r - len(keep_r)], "header_rows_1week": pt.header_rows,
            "invisible_edges_dropped": n_inv, "closed_sides": closed,
            "grid_xs": [round(x, 1) for x in xs], "grid_ys": [round(y, 1) for y in ys],
            "col_x": [round(x, 1) for x in col_x], "row_y": [round(y, 1) for y in row_y],
            "grid_ok": pt.grid_check.ok, "char_ok": pt.char_check.ok, "notes_1week": pt.notes,
            # 검증용: 칸 (병합 칸은 한 번)의 한글 음절 수. 머리·몸 격자는 병합 칸 글자를 걸친 칸마다 되풀이한다
            "cell_hangul": sum(len(re.findall("[가-힣]", c.text)) for c in pt.cells)}


def notes_below(t: dict, lines: list[dict], used: set) -> tuple[list[str], list[int]]:
    x0, top, x1, bottom = t["bbox"]
    cand = sorted([d for d in lines if d["top"] >= bottom - 1 and d["line_id"] not in used and d["zone"] != "table"
                   and not d["is_page_number"]], key=lambda d: d["top"])
    notes, ids, prev = [], [], None
    for d in cand:
        gap = d["top"] - (prev["bottom"] if prev else bottom)
        pat = d["pattern"]
        if prev is None:
            if pat not in NOTE_PATTERNS or gap > P("table_extract.note_gap_pt"):
                break
            notes.append(d["text"].strip())
        elif pat in NOTE_PATTERNS and gap <= P("table_extract.note_gap_pt"):
            notes.append(d["text"].strip())
        elif gap <= P("table_extract.note_cont_gap_pt") and pat not in NUMBERED:
            notes[-1] = notes[-1] + " " + d["text"].strip()
        else:
            break
        ids.append(d["line_id"])
        prev = d
    return notes, ids


def caption_near(t: dict, lines: list[dict], used: set) -> dict | None:
    """표 설명 줄 (프로필 caption_patterns, 표 종류): 표 아래 (주석 다음) 또는 위 table_extract.caption_gap_pt 안의
    가장 가까운 줄이 설명 모양이면 {page, line_id, text, where}."""
    x0, top, x1, bottom = t["bbox"]
    gap = P("table_extract").get("caption_gap_pt", 30.0)
    body = [d for d in lines if d["zone"] != "table" and not d["is_page_number"] and d["line_id"] not in used]
    below = sorted([d for d in body if d["top"] >= bottom - 1 and d["top"] - bottom <= gap], key=lambda d: d["top"])
    above = sorted([d for d in body if d["bottom"] <= top + 1 and top - d["bottom"] <= gap], key=lambda d: -d["bottom"])
    for where, cand in (("below", below[:1]), ("above", above[:1])):
        for d in cand:
            k = caption_kind(d["text"])
            if k and k[0] == "table":
                return {"page": t["page"], "line_id": d["line_id"], "text": d["text"].strip(), "where": where}
    return None


def tidy_rows(rec: dict, vocab=None) -> None:
    """보고서 표 다듬기 (설정이 켜졌을 때): 칸 안 줄 잇기 (smart_line_join, 단어 중간 줄바꿈은 붙임), 칸의 위첨자
    각주 번호 빼기 (덤프 footnote_refs의 번호가 글자 바로 뒤에 "5)"·"(5)"로 붙은 것), 칸 공백 정리
    (table_extract.normalize_spaces), 1열 표 (상자 도식)에서 글머리표·번호로 시작하지 않는 행은 위 행에 잇기
    (table_extract.merge_single_col_rows)."""
    def fix(c):
        c = c or ""
        if LINE_SEP in c:
            c = join_lines(c.split(LINE_SEP), vocab)
        for k in rec.get("footnote_refs", []):
            c = re.sub(rf"(?<=[^\s(])\(?{k}\)", "", c)
        return c

    rec["header"] = [[fix(c) for c in r] for r in rec["header"]]
    rec["rows"] = [[fix(c) for c in r] for r in rec["rows"]]
    te = P("table_extract")
    if te.get("normalize_spaces"):
        rec["header"] = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rec["header"]]
        rec["rows"] = [[re.sub(r"\s+", " ", c or "").strip() for c in r] for r in rec["rows"]]
    if te.get("merge_single_col_rows") and rec["n_cols"] == 1 and len(rec["rows"]) > 1:
        out_ = []
        for r in rec["rows"]:
            txt = (r[0] if r else "") or ""
            if out_ and txt and not ROW_START_RE.match(txt) and ROW_START_RE.match(out_[-1][0] or ""):
                out_[-1] = [(out_[-1][0] + " " + txt).strip()]
            else:
                out_.append([txt])
        rec["rows_merged_single_col"] = len(rec["rows"]) - len(out_)
        rec["rows"] = out_


def is_title_line(d: dict) -> bool:
    title_fonts = set(fonts_of("title_band") + [font("article_title"), font("gwan_title"), font("pyeon_title")])
    body_size = float(font("body").split("/")[1])
    return d["bold_ratio"] > 0.5 or d["font_key"] in title_fonts or d["size"] > body_size + 0.5


def upper_context(t: dict, page_lines: dict[int, list[dict]], marked: dict) -> dict:
    p = t["page"]
    x0, top, x1, _ = t["bbox"]

    def usable(q, d):
        return not d["is_page_number"] and not marked.get((q, d["line_id"])) and d["region_id"] != t["source"]

    above = [d for d in page_lines[p] if usable(p, d) and d["bottom"] <= top + 1 and d["x1"] > x0 and d["x0"] < x1]
    above.sort(key=lambda d: d["bottom"])
    res = {"title": None, "intro": None, "prev_numbered": None}
    if above:
        near = above[-1]
        if top - near["bottom"] <= P("table_extract.title_gap_pt") and is_title_line(near):
            res["title"] = {"page": p, "line_id": near["line_id"], "text": near["text"].strip()}
            rest = [d for d in above if d["bottom"] <= near["top"] + 1]
            if rest and near["top"] - rest[-1]["bottom"] <= P("table_extract.title_gap_pt"):
                res["intro"] = {"page": p, "line_id": rest[-1]["line_id"], "text": rest[-1]["text"].strip()}
        elif top - near["bottom"] <= P("table_extract.intro_gap_pt"):
            res["intro"] = {"page": p, "line_id": near["line_id"], "text": near["text"].strip()}
    pages = [q for q in INCLUDED_PAGES if q <= p][::-1][:3]
    for q in pages:
        cand = [d for d in page_lines[q] if usable(q, d) and d["zone"] == "body" and d["pattern"] in NUMBERED
                and (q < p or d["bottom"] <= top + 1)]
        if cand:
            d = max(cand, key=lambda d: d["top"])
            res["prev_numbered"] = {"page": q, "line_id": d["line_id"], "pattern": d["pattern"], "text": d["text"].strip()}
            break
    return res


def body_above_below(t: dict, page_lines: list[dict], marked: dict, notes_ids: set) -> tuple[int, int]:
    p, (x0, top, x1, bottom) = t["page"], t["bbox"]
    ok = [d for d in page_lines if not d["is_page_number"] and not marked.get((p, d["line_id"])) and d["region_id"] != t["source"]
          and d["line_id"] not in notes_ids]
    return sum(1 for d in ok if d["bottom"] <= top + 1), sum(1 for d in ok if d["top"] >= bottom - 1)


def checks(rec: dict) -> list[str]:
    flags = []
    rows = rec["rows"]
    if not rows:
        return ["no_rows"]
    if rec["shape"] == "c":
        flags.append("image_cells")
    if rec["method"] == "grid" and not (rec.get("grid_ok") and rec.get("char_ok")):
        flags.append("grid_check_failed")
    lens = {len(r) for r in rows}
    if len(lens) > 1:
        flags.append("col_mismatch")
    cells = [c for r in rows for c in r]
    if cells and sum(1 for c in cells if not c) / len(cells) > P("table_extract.empty_ratio_low"):
        flags.append("many_empty")
    n_cols = max(lens)
    for k in range(n_cols):
        col = [r[k] for r in rows if k < len(r) and r[k]]
        if len(col) >= 3 and sum(1 for c in col if NUM_RE.match(c)) / len(col) >= P("table_extract.numeric_col_ratio"):
            if any(not NUM_RE.match(c) for c in col):
                flags.append("numeric_col_nonnumeric")
                break
    return flags


def main() -> int:
    setup("tables_extract")
    import pdfplumber

    cfg, load_page_geometry, split_regions, parse_table, _ = load_week1()
    regs = [json.loads(s) for s in (TABLE_DIR / "table_regions.jsonl").read_text(encoding="utf-8").splitlines()]
    tables = sorted([r for r in regs if r["decided"] == "table"], key=lambda r: (r["page"], r["bbox"][1]))
    marked = load_marked()
    page_lines = {p: lines_of(p) for p in INCLUDED_PAGES}
    vocab = None
    if profile().get("smart_line_join"):  # 칸 안 줄은 표시 글자로 이어 두고 tidy_rows에서 단어 경계를 보고 잇는다
        cfg.cell_line_join = LINE_SEP
        vocab = Vocab(d["text"] for p in INCLUDED_PAGES for d in page_lines[p])
    recs = []
    geoms: dict = {}
    for t in tables:
        p = t["page"]
        if t["shape"] == "a":
            if p not in geoms:
                geoms = {p: (page_geometry(p), page_objects(p))}  # 덤프에 저장한 선분·글자·그리기 객체로 (PDF를 다시 열지 않음)
            ex = extract_a(t, *geoms[p], cfg, split_regions, parse_table)
        elif t["shape"] == "d":
            ex = extract_d(t, cfg.cell_line_join)
        else:
            ex = extract_cols(t, cfg.cell_line_join)
        notes, note_ids = notes_below(t, page_lines[p], set())
        cap = caption_near(t, page_lines[p], set(note_ids))
        refs = sorted({k for d in page_lines[p] if d["region_id"] == t["source"] for k in d.get("footnote_refs", [])})
        # 설명 줄은 표 아래 글로 센다 (설명이 붙은 표는 거기서 끝: 다음 쪽 표와 잇지 않음)
        above, below = body_above_below(t, page_lines[p], marked, set(note_ids))
        rec = {"table_id": t["table_id"], "pages": [p], "page": p, "zone": t["zone"], "bbox": t["bbox"], "bboxes": [t["bbox"]],
               "shape": t["shape"], "step": t["step"], "set": t.get("set"), **ex, "notes": notes, "note_line_ids": note_ids,
               "body_above": above, "body_below": below, **upper_context(t, page_lines, marked), "caption": cap,
               "footnote_refs": refs}
        if cap and rec["title"] is None:
            rec["title"] = {k: cap[k] for k in ("page", "line_id", "text")}
        recs.append(rec)

    # 쪽 넘김 이어 붙이기
    merged, by_page = [], defaultdict(list)
    for r in recs:
        by_page[r["page"]].append(r)
    n_merge = 0
    inc = INCLUDED_PAGES
    for r in recs:  # 쪽마다 칸 좌표 (확인 그림용). 이어 붙인 표도 쪽마다 자기 좌표로 그린다
        r["page_draw"] = [{k: r[k] for k in DRAW_KEYS if k in r}]
    for r in recs:
        prev_pages = [q for q in inc if q < r["page"]]
        pq = prev_pages[-1] if prev_pages else None
        prev_last = merged[-1] if merged else None
        if (pq is not None and prev_last is not None and prev_last["pages"][-1] == pq and r is by_page[r["page"]][0]
                and r["body_above"] == 0 and prev_last["body_below"] == 0 and r["shape"] == prev_last["shape"]
                and (not r["header"] or r["header"] == prev_last["header"])  # 쪽마다 같은 머리 행을 반복하는 표
                and r["n_cols"] == prev_last["n_cols"]
                and all(abs(a - b) <= P("table_extract.col_match_tol_pt") for a, b in zip(r["col_x"], prev_last["col_x"]))):
            rows = r["rows"]
            if (P("table_extract").get("join_split_rows") and rows and prev_last["rows"] and len(rows[0]) > 1
                    and not (rows[0][0] or "").strip() and any((c or "").strip() for c in rows[0][1:])
                    and len(rows[0]) == len(prev_last["rows"][-1])):
                # 쪽 경계에서 잘린 행: 다음 쪽 첫 행의 첫 칸이 비면 앞 쪽 마지막 행에 잇는다
                prev_last["rows"][-1] = [((a or "") + " " + (b or "")).strip() for a, b in zip(prev_last["rows"][-1], rows[0])]
                prev_last["split_rows_joined"] = prev_last.get("split_rows_joined", 0) + 1
                rows = rows[1:]
            prev_last["rows"] += rows
            prev_last["pages"].append(r["page"])
            prev_last["bboxes"].append(r["bbox"])
            prev_last["page_draw"] += r["page_draw"]
            if "cell_hangul" in r:
                prev_last["cell_hangul"] = prev_last.get("cell_hangul", 0) + r["cell_hangul"]
            prev_last["notes"] += r["notes"]
            prev_last["footnote_refs"] = sorted(set(prev_last.get("footnote_refs", [])) | set(r.get("footnote_refs", [])))
            if r.get("caption"):  # 설명 줄은 마지막 쪽 것. 제목이 없거나 앞 설명에서 온 것이면 새 설명으로
                old = prev_last.get("caption")
                if prev_last["title"] is None or (old and prev_last["title"].get("line_id") == old["line_id"]):
                    prev_last["title"] = {k: r["caption"][k] for k in ("page", "line_id", "text")}
                prev_last["caption"] = r["caption"]
            prev_last["merged_ids"] = prev_last.get("merged_ids", []) + [r["table_id"]]
            prev_last["repeated_header_dropped"] = prev_last.get("repeated_header_dropped", 0) + bool(r["header"])
            prev_last["body_below"] = r["body_below"]
            n_merge += 1
            continue
        merged.append(r)
    for r in merged:
        tidy_rows(r, vocab)
        r["flags"] = checks(r)
        r["confidence"] = "low" if set(r["flags"]) & {"no_rows", "image_cells", "grid_check_failed", "col_mismatch",
                                                         "many_empty", "numeric_col_nonnumeric"} else "ok"
    with open(secure_path(TABLE_DIR / "tables.jsonl"), "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_flagged = 0
    if review_mode():
        from review.tables_extract import write_examples, write_flagged_check, write_report, write_user_check
        write_report(merged, n_merge)
        write_examples(merged)
        write_user_check(merged)
        n_flagged = write_flagged_check(merged)
    out("done", tables=len(merged), merged_cross_page=n_merge, low=sum(r["confidence"] == "low" for r in merged),
        flagged_for_user=n_flagged,
        flags=dict(Counter(f for r in merged for f in r["flags"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
