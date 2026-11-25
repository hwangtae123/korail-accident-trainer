"""2단계: PDF 문자 기준선. 샘플 쪽을 pdfplumber로 줄 단위 덤프한다 (1week-rag 코드는 import만).

출력 (원문 포함 → secure): secure/lines/by_page/pNNN.json (쪽마다 meta·lines·chars·regions·dropped, 있으면 건너뜀,
  --force로 다시), 묶음 secure/lines/{regions.json, regions_dropped.json, pages.json}
대상 쪽: 샘플·구역 확인 쪽 (DUMP_PAGES)과 포함 쪽 (INCLUDED_PAGES)
확인용 출력 (--report, parsing/review/pdf_lines.py): results/parsing/pdf_baseline.md (집계만), 박스 라벨 발췌
실행 (requirements.txt 환경): python parsing/pdf_lines.py

- 영역: 1week-rag split_regions + parse_table. 표 (행 또는 열 2개 이상)는 격자·글자 검사 결과를 같이 남기고,
  1×1 상자는 box. 글자 영역은 중심점 기준 (bbox ± snap_tol), 표 주석은 표 bottom 아래 notes_bottom까지.
- 줄: 영역마다 따로 _group_lines로 묶는다 (줄 상자가 영역 경계를 넘지 않게).
- 쪽번호: 쪽의 가장 아래 줄 (표 밖)이 숫자만 (앞뒤 줄표 허용: "- 5 -")이고 가로 가운데 ± page_number.center_tol_pt 안이면
  본문에서 빼고 값은 pages.json에 남긴다.
- 띄어쓰기: 프로필 space_gap_ratio가 있으면 (공백 글자 없이 만든 PDF. 한글 문서 편집기에서 내보낸 보고서 등) 같은 줄의
  이웃 글자 사이가 글자 크기 × 이 비율보다 넓을 때 공백 글자를 넣는다 (표·칸·줄 글자 모두 이 글자 목록을 쓴다).
  철도사고 보고서 4종에서 단어 안 간격 ≤ 0.1, 단어 사이 0.3~0.8 (글자 크기 배수).
- 글자 바꾸기: 프로필 char_map (예: 『』가 사용자 정의 영역 글자 U+F000으로 들어간 PDF).
- 위첨자 각주 번호: 프로필 superscript_refs면 줄 안에 작게 붙은 숫자·괄호 ("열차2)")를 줄 글자에서 빼고
  줄의 footnote_refs에 번호로 남긴다 (트리가 각주를 이 번호가 나온 노드에 붙인다).
- rel_x 기준: 표 밖 본문 폰트 (프로필 fonts.body) 줄 최소 x0 → 없으면 표 밖 전체 줄 최소 x0 → 없으면 전체 줄 최소 x0.
- 덤프가 끝나면 프로필 폰트 확인 (config.check_profile) 결과를 경고로 내고 results/parsing/profile_check.md에 쓴다.
설정: config/profiles/<프로필>.yaml (폰트·박스 라벨), config/params.yaml, 문서는 config/docs/<doc_id>.yaml.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safeio import ROOT, RESULTS, SECURE, Trusted, rel, out, result_path, review_mode, secure_path, setup  # noqa: E402

# 1주차 표 파서 (policy_rag) 복사본. 1주차 저장소 없이 돈다 (출처·기준 커밋은 vendor/SOURCE.txt)
WEEK1 = ROOT / "vendor"
sys.path.insert(0, str(WEEK1))

from config import P, base_font, box_labels, check_profile, doc_pdf, font, is_bold_font, profile  # noqa: E402
from samples import DUMP_PAGES, INCLUDED_PAGES, SAMPLE45  # noqa: E402

LINES_DIR = SECURE / "lines"
BY_PAGE_DIR = LINES_DIR / "by_page"

# 3주차 실패 모양 (handoff_3week.md 5절)
WEEK3_GRID_4X4 = [[0, 0, 1, 3], [0, 3, 4, 1], [1, 0, 2, 3], [3, 0, 1, 3]]

# 줄 맨 앞 패턴 (앞 공백 무시). 위에서부터 먼저 맞는 것.
PATTERNS = [
    ("pyeon", re.compile(r"제\s*\d+\s*편")),
    ("gwan", re.compile(r"제\s*\d+\s*관")),
    ("art_nm", re.compile(r"제\s*\d+\s*-\s*\d+\s*조")),
    ("art_n", re.compile(r"제\s*\d+\s*조")),
    ("circled", re.compile("[①-⑳]")),
    ("num_dot", re.compile(r"\d+\.(?!\d)")),
    ("hangul_dot", re.compile("[가나다라마바사아자차카타파하]\\.")),
    ("num_paren", re.compile(r"\d+\)")),
    ("hangul_paren", re.compile("[가나다라마바사아자차카타파하]\\)")),
    ("note_ju", re.compile(r"\(\s*주\s*\)")),
    ("paren_num", re.compile("\\(\\d+\\)|[⑴-⒇]")),
    ("paren_hangul", re.compile("\\([가나다라마바사아자차카타파하]\\)")),
    ("bullet", re.compile("[□■○●◆◇▶▷]")),
    ("note_ref", re.compile("※")),
    ("note_cju", re.compile("㈜")),
    ("digits_only", re.compile(r"\d+\s*$")),
]
# 박스 라벨 패턴 (줄 맨 앞, 여는 괄호류 허용): 라벨 단어는 회사 스타일 프로필 (box_labels). 글자 사이 공백 허용,
# 뒤에 한글이 바로 이어지면 낱말 일부로 보고 제외. box_exN은 예시 키워드 첫 글자 + 숫자 + ")" 모양.
_OPEN = "[\\[<〈【(]?\\s*"
_EX = profile()["example"]["keyword"]
BOX_PATTERNS = [(kind, re.compile(_OPEN + "\\s*".join(word) + "(?![가-힣])")) for kind, word in box_labels().items()]
BOX_PATTERNS.append(("box_exN", re.compile(_OPEN + _EX[0] + "\\s*\\d+\\s*\\)")))
PAGE_NUMBER_TOL = P("page_number.center_tol_pt")
is_bold = is_bold_font


def line_pattern(text: str) -> str:
    s = text.lstrip()
    for name, rx in PATTERNS:
        if name == "digits_only":
            if rx.match(s) and s.strip().isdigit():
                return name
        elif rx.match(s):
            return name
    return "none"


def box_pattern(text: str) -> str | None:
    s = text.lstrip()
    for name, rx in BOX_PATTERNS:
        if rx.match(s):
            return name
    return None


def box_pattern_anywhere(text: str) -> list[str]:
    """줄 안 어디든 박스 라벨 모양이 있는 패턴 이름 (진단용, 줄 맨 앞 규칙이 놓치는 양을 보려고)."""
    return [name for name, rx in BOX_PATTERNS if rx.search(text)]


def load_week1():
    from policy_rag.config import load_config
    from policy_rag.ingest.extract import load_page_geometry
    from policy_rag.ingest.tables import _group_lines, parse_table, split_regions

    cfg = load_config(str(WEEK1 / "policy_rag" / "config.yaml"))
    return cfg, load_page_geometry, split_regions, parse_table, _group_lines


def add_gap_spaces(chars: list, ratio: float, group_lines) -> list:
    """공백 글자가 없는 PDF: 같은 줄 이웃 글자 간격 > 글자 크기 × ratio이면 그 사이에 공백 글자를 넣는다."""
    from policy_rag.ingest.extract import Char

    out_ = list(chars)
    for g in group_lines(chars):  # 원래 공백 글자도 같이 묶어, 그 옆 간격에는 넣지 않는다 (폭 0인 공백 글자가 있는 PDF)
        for a, b in zip(g, g[1:]):
            if a.text.isspace() or b.text.isspace():
                continue
            size = max(a.size, b.size, 1.0)
            if b.x0 - a.x1 > ratio * size:
                out_.append(Char(" ", a.x1, b.x0, min(a.top, b.top), max(a.bottom, b.bottom), a.fontname, a.size))
    return out_


def map_chars(chars: list, cmap: dict, group_lines) -> None:
    """프로필 char_map: 글자 층의 잘못된 글자를 바꾼다. 값이 목록이면 쪽 읽기 순서로 번갈아 (예: 『와 』가 같은 사용자 정의
    영역 글자 U+F000으로 들어간 PDF → 『, 』, 『, …)."""
    turn = {k: 0 for k in cmap}
    for g in group_lines(chars):
        if sum(not c.text.isspace() for c in g) < 3:  # 기호 하나뿐인 줄 (같은 코드의 화살표 그림 등)은 그대로
            continue
        for c in g:
            k = c.text
            v = cmap.get(k)
            if v is None:
                continue
            if isinstance(v, list):
                c.text = v[turn[k] % len(v)]
                turn[k] += 1
            else:
                c.text = v


SUP_CHARS = set("0123456789()")


def superscripts(g: list) -> tuple[set, list[int]]:
    """줄 안 위첨자 각주 번호 ("열차²⁾"처럼 작게 붙은 숫자·괄호): 줄 글자 크기 중앙값의 0.8배 이하인 숫자·괄호가
    이어진 4글자 이하 묶음 (숫자 포함, 줄 맨 앞 아님). 반환: (그 글자 id 집합, 번호 목록)."""
    vis = [c for c in g if not c.text.isspace()]
    if len(vis) < 4:
        return set(), []
    m = median(c.size for c in vis)
    ids, refs, run = set(), [], []

    def flush():
        txt = "".join(c.text for c in run)
        if run and len(run) <= 4 and any(ch.isdigit() for ch in txt) and run[0] is not vis[0]:
            ids.update(id(c) for c in run)
            refs.append(int("".join(ch for ch in txt if ch.isdigit())))
        run.clear()

    for c in vis:
        if c.text in SUP_CHARS and c.size <= 0.8 * m:
            run.append(c)
        else:
            flush()
    flush()
    return ids, refs


PAGE_NO_RE = re.compile(r"[-–—\s]*(\d+)[-–—\s]*")


def page_regions(geom, cfg, split_regions, parse_table) -> list[dict]:
    tables, boxes = split_regions(geom, cfg)
    regs = []
    for i, region in enumerate(tables):
        below = [r.bbox[1] for r in tables if r.bbox[1] >= region.bbox[3] - cfg.snap_tol]
        t = parse_table(geom, region, cfg, min(below) if below else None)
        merges = sorted([c.row, c.col, c.rowspan, c.colspan] for c in t.cells if c.rowspan > 1 or c.colspan > 1)
        shape = f"{t.grid.n_rows}x{t.grid.n_cols}"
        week3 = None
        if not t.grid_check.ok and shape == "4x4" and merges == WEEK3_GRID_4X4:
            week3 = "grid_4x4_merge"
        elif not t.char_check.ok and shape in ("2x10", "2x1"):
            week3 = f"char_{shape}"
        regs.append({
            "page": geom.page, "region_id": f"p{geom.page}#t{i}", "kind": "table", "bbox": t.bbox,
            "n_rows": t.grid.n_rows, "n_cols": t.grid.n_cols, "shape": shape, "merges": merges,
            "grid_ok": t.grid_check.ok, "char_ok": t.char_check.ok, "week3_shape": week3,
            "notes_bottom": t.notes_bottom,
        })
    for j, region in enumerate(boxes):
        regs.append({"page": geom.page, "region_id": f"p{geom.page}#b{j}", "kind": "box", "bbox": list(region.bbox),
                     "n_rows": 1, "n_cols": 1, "shape": "1x1", "merges": [], "grid_ok": True, "char_ok": True,
                     "week3_shape": None, "notes_bottom": None})
    return regs


def _inside(a, b, tol: float) -> bool:
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def _fill_only_edges(page, bbox, tol: float | None = None) -> bool:
    """영역 경계에 닿는 그리기 객체가 있고, 그것이 모두 채움 전용 사각형 (fill=True, stroke=False)인지."""
    tol = P("phantom_region.edge_touch_tol_pt") if tol is None else tol
    x0, top, x1, bottom = bbox
    touching = []
    for kind, objs in (("line", page.lines), ("rect", page.rects), ("curve", page.curves)):
        for o in objs:
            ob = [float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"])]
            if not _inside(ob, bbox, tol):
                continue
            if min(abs(ob[0] - x0), abs(ob[2] - x1), abs(ob[1] - top), abs(ob[3] - bottom)) <= tol:
                touching.append((kind, bool(o.get("fill")), bool(o.get("stroke"))))
    return bool(touching) and all(k == "rect" and f and not s for k, f, s in touching)


def drop_phantoms(page, regs: list[dict], chars, tol: float) -> tuple[list[dict], list[dict]]:
    """1-0: 다른 영역 안에 있고, 글자 0개 (영역 배정 기준)이고, 테두리가 채움 사각형으로만 만들어진 영역을 뺀다.

    글자가 있는 중첩 영역은 남기고 nested=True로 표시한다. region_id는 다시 매기지 않는다 (다른 결과와 맞추기 위해).
    """
    owned = Counter(char_zone(c, regs, tol)[1] for c in chars if not c.text.isspace())
    kept, dropped = [], []
    for r in regs:
        outer = next((o for o in regs if o is not r and _inside(r["bbox"], o["bbox"], P("phantom_region.inside_tol_pt"))), None)
        r["nested"] = outer is not None
        r["outer_id"] = outer["region_id"] if outer else None
        if outer is not None and owned.get(r["region_id"], 0) == 0 and _fill_only_edges(page, r["bbox"]):
            dropped.append({**r, "drop_reason": "phantom_fill_only"})
        else:
            kept.append(r)
    return kept, dropped


def char_zone(ch, regs: list[dict], tol: float) -> tuple[str, str | None]:
    cx, cy = (ch.x0 + ch.x1) / 2, (ch.top + ch.bottom) / 2
    for kind in ("table", "box"):
        for r in regs:
            if r["kind"] != kind:
                continue
            x0, top, x1, bottom = r["bbox"]
            if x0 - tol <= cx <= x1 + tol and top - tol <= cy <= bottom + tol:
                return kind, r["region_id"]
            if kind == "table" and r["notes_bottom"] is not None and bottom + tol < cy <= r["notes_bottom"]:
                return "note", r["region_id"]
    return "body", None


def build_lines(geom, regs, cfg, group_lines) -> list[dict]:
    sup_on = bool(profile().get("superscript_refs"))
    groups: dict[tuple[str, str | None], list] = defaultdict(list)
    for ch in geom.chars:
        groups[char_zone(ch, regs, cfg.snap_tol)].append(ch)
    lines = []
    for (zone, rid), chars in groups.items():
        for g in group_lines(chars):
            sup, refs = superscripts(g) if sup_on else (set(), [])
            text = "".join(c.text for c in g if id(c) not in sup)
            if not text.strip():
                continue
            vis = [c for c in g if not c.text.isspace()]
            font = Counter(base_font(c.fontname) for c in vis).most_common(1)[0][0]
            size = median(c.size for c in vis)
            lines.append({
                "page": geom.page, "zone": zone, "region_id": rid, "text": text,
                "x0": round(g[0].x0, 2), "x1": round(max(c.x1 for c in g), 2),
                "top": round(min(c.top for c in g), 2), "bottom": round(max(c.bottom for c in g), 2),
                "font": font, "size": round(size, 2), "font_key": f"{font}/{round(size, 1):g}",
                "bold_ratio": round(sum(is_bold(c.fontname) for c in vis) / len(vis), 3),
                "n_chars": len(vis), "pattern": line_pattern(text), "box_pattern": box_pattern(text),
                "box_pattern_any": box_pattern_anywhere(text),
                **({"footnote_refs": refs} if refs else {}),
                "_chars": g,
            })
    lines.sort(key=lambda d: (d["top"], d["x0"]))
    return lines


def mark_page(lines: list[dict], width: float) -> dict:
    meta: dict = {"page_number": None, "page_number_removed": False}
    non_table = [d for d in lines if d["zone"] != "table"]
    if lines:  # 쪽 맨 아래 줄이 줄표 쪽번호 ("- 7 -")면 표 영역 (쪽 테두리 상자 등) 안이어도 쪽번호
        bottom = max(lines, key=lambda d: d["bottom"])
        if PAGE_NO_RE.fullmatch(bottom["text"].strip()) and any(ch in bottom["text"] for ch in "-–—"):
            non_table = [bottom]
    if non_table:
        last = max(non_table, key=lambda d: d["bottom"])
        m = PAGE_NO_RE.fullmatch(last["text"].strip())
        dashed = any(ch in last["text"] for ch in "-–—")
        # 줄표 쪽번호 ("- 7 -")는 모양이 분명해 가운데 검사를 하지 않는다 (좌우 여백이 다른 보고서는 10pt 넘게 어긋남)
        if m and (dashed or abs((last["x0"] + last["x1"]) / 2 - width / 2) <= PAGE_NUMBER_TOL):
            last["is_page_number"] = True
            meta.update(page_number=int(m.group(1)), page_number_removed=True,
                        page_number_offset=round((last["x0"] + last["x1"]) / 2 - width / 2, 2))
    body = [d for d in lines if not d.get("is_page_number")]
    cand = [d for d in body if d["zone"] != "table" and d["font_key"] == font("body")]
    kind = "slil10_non_table"
    if not cand:
        cand, kind = [d for d in body if d["zone"] != "table"], "all_non_table"
    if not cand:
        cand, kind = body, "all_lines"
    base = min((d["x0"] for d in cand), default=0.0)
    meta.update(rel_x_base=base, rel_x_kind=kind)
    for i, d in enumerate(lines):
        d["line_id"] = i
        d.setdefault("is_page_number", False)
        d["rel_x"] = round(d["x0"] - base, 2)
    return meta


def md_table(headers: list[str], rows: list[list]) -> str:
    def cell(v):
        return f"{v:.1f}" if isinstance(v, float) else str(v)
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def _color(c):
    """채움 색 (회색조·RGB·CMYK 숫자 목록). 패턴 채움 (색 대신 'Pa1' 같은 이름)은 None."""
    if c is None:
        return None
    try:
        return [float(v) for v in c] if isinstance(c, (list, tuple)) else [float(c)]
    except (TypeError, ValueError):
        return None


def page_objects_dump(page, geom) -> dict:
    """뒤 단계 (boxes, tables_classify, tables_extract)가 PDF를 다시 읽지 않도록 그리기 객체를 원래 정밀도로 남긴다.

    segments: 1week 표 감지용 선분 [orient, pos, start, end], rects/lines: 좌표·채움·테두리·채움 색, curves: 좌표,
    chars_raw: 1week 표 파싱용 글자 좌표 (geom.chars 순서, [x0, x1, top, bottom, size]).
    """
    def box(o):
        return {"x0": float(o["x0"]), "x1": float(o["x1"]), "top": float(o["top"]), "bottom": float(o["bottom"])}

    return {
        "segments": [[s.orient, s.pos, s.start, s.end] for s in geom.segments],
        "rects": [{**box(o), "fill": bool(o.get("fill")), "stroke": bool(o.get("stroke")),
                   "non_stroking_color": _color(o.get("non_stroking_color"))} for o in page.rects],
        "lines": [{**box(o), "fill": bool(o.get("fill")), "stroke": bool(o.get("stroke"))} for o in page.lines],
        "curves": [box(o) for o in page.curves],
        "chars_raw": [[c.x0, c.x1, c.top, c.bottom, c.size] for c in geom.chars],
        "obj_counts": geom.obj_counts,
    }


def write_profile_check(font_chars: Counter) -> None:
    """프로필 폰트 확인 결과를 경고로 내고 results/parsing/profile_check.md에 쓴다 (폰트 키·글자 수만)."""
    warns = check_profile(font_chars)
    for w in warns:
        out("profile_warn", code=Trusted(w))
    total = sum(font_chars.values())
    roles = {fk: role for role in profile()["fonts"] for v in [font(role)] for fk in (v if isinstance(v, list) else [v])}
    rows = [[fk, n, f"{100 * n / total:.2f}%", roles.get(fk, "")] for fk, n in font_chars.most_common(15)]
    parts = ["# 회사 스타일 프로필 확인 (포함 쪽 글자 기준)", "",
             f"문서 {Trusted(str(doc_pdf().name))}, 공백 아닌 글자 {total}.", "",
             md_table(["폰트", "글자", "비율", "프로필 역할"], rows), "",
             "경고: " + (", ".join(warns) if warns else "없음"), ""]
    if review_mode():  # 경고는 항상, 파일은 확인 모드에서만
        result_path(RESULTS / "parsing" / "profile_check.md").write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    setup("pdf_lines")
    import pdfplumber

    cfg, load_page_geometry, split_regions, parse_table, group_lines = load_week1()
    pdf_path = doc_pdf()
    force = "--force" in sys.argv
    gap_ratio = profile().get("space_gap_ratio")
    char_map = profile().get("char_map") or {}
    targets = sorted(set(DUMP_PAGES) | set(INCLUDED_PAGES))
    pdf = pdfplumber.open(pdf_path)
    n_done = 0
    for p in targets:
        path = BY_PAGE_DIR / f"p{p:03d}.json"
        if path.exists() and not force:
            continue
        geom = load_page_geometry(str(pdf_path), p, cfg)
        if gap_ratio:
            geom.chars = add_gap_spaces(geom.chars, gap_ratio, group_lines)
        if char_map:
            map_chars(geom.chars, char_map, group_lines)
        regs, dropped = drop_phantoms(pdf.pages[p - 1], page_regions(geom, cfg, split_regions, parse_table),
                                      geom.chars, cfg.snap_tol)
        objects = page_objects_dump(pdf.pages[p - 1], geom)
        pdf.pages[p - 1].flush_cache()
        lines = build_lines(geom, regs, cfg, group_lines)
        meta = mark_page(lines, geom.width)
        in_line = {}
        for d in lines:
            for c in d.pop("_chars"):
                in_line[id(c)] = d["line_id"]
        chars = []
        for c in geom.chars:
            zone, rid = char_zone(c, regs, cfg.snap_tol)
            chars.append({"page": p, "text": c.text, "x0": round(c.x0, 2), "x1": round(c.x1, 2),
                          "top": round(c.top, 2), "bottom": round(c.bottom, 2), "font": base_font(c.fontname),
                          "size": round(c.size, 2), "bold": is_bold(c.fontname), "zone": zone, "region_id": rid,
                          "line_id": in_line.get(id(c))})
        meta.update(width=geom.width, height=geom.height, n_chars=sum(not c.text.isspace() for c in geom.chars),
                    n_images=len(geom.image_bboxes), image_bboxes=geom.image_bboxes)
        secure_path(path).write_text(json.dumps({"meta": meta, "lines": lines, "chars": chars, "regions": regs,
                                                 "dropped": dropped, "objects": objects}, ensure_ascii=False), encoding="utf-8")
        n_done += 1
        if n_done % 50 == 0:
            out("progress", page=p, dumped=n_done)
    pdf.close()

    # 쪽별 파일에서 작은 묶음 파일 (쪽 정보, 영역, 버린 영역)을 다시 만든다
    pages, all_regions, all_dropped = {}, [], []
    font_chars: Counter = Counter()  # 포함 쪽의 공백 아닌 글자 폰트 분포 (프로필 확인용)
    inc = set(INCLUDED_PAGES)
    for p in targets:
        d = json.loads((BY_PAGE_DIR / f"p{p:03d}.json").read_text(encoding="utf-8"))
        pages[p] = d["meta"]
        all_regions += d["regions"]
        all_dropped += d["dropped"]
        if p in inc:
            font_chars.update(f"{c['font']}/{round(c['size'], 1):g}" for c in d["chars"] if c["text"].strip())
    secure_path(LINES_DIR / "regions.json").write_text(json.dumps(all_regions), encoding="utf-8")
    secure_path(LINES_DIR / "regions_dropped.json").write_text(json.dumps(all_dropped), encoding="utf-8")
    secure_path(LINES_DIR / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    out("done", pages=len(pages), newly_dumped=n_done, regions=len(all_regions), dropped=len(all_dropped),
        nested_kept=sum(r["nested"] for r in all_regions))
    write_profile_check(font_chars)
    if "--report" in sys.argv:  # 2단계 리포트는 기본으로는 다시 쓰지 않는다
        from review.pdf_lines import write_box_label_review, write_report
        s45 = set(SAMPLE45)
        lines45 = [d for p in SAMPLE45 for d in json.loads((BY_PAGE_DIR / f"p{p:03d}.json").read_text(encoding="utf-8"))["lines"]]
        write_box_label_review(lines45)
        report = write_report(lines45, {p: m for p, m in pages.items() if p in s45},
                              [r for r in all_regions if r["page"] in s45])
        out("report", path=Trusted(rel(report)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
