"""2차 2단계 2-1: 표 영역 확정과 선 모양 분류 (포함 쪽만, 제외 영역 안의 표는 다루지 않는다).

영역 종류 결정 (pdfplumber 영역 중 글자가 있는 것만):
  제목 띠: 영역 안에 제목 띠 폰트 (프로필 fonts.title_band) 줄이 있으면 표가 아니라 제목 띠
  ② 박스 라벨 (설명·유의사항·용어 해설) 인식 → 박스 (이번 단계 대상 아님). 격자 검사를 통과해도 박스 (①보다 먼저)
  ① pdfplumber 표 검사 (격자·글자 배정) 통과 → 표
  ③ 그 밖 → 글자 행이 tables.geo_table_min_rows 이상이고 라벨 열 구분 (boxes.find_separator)이나 안쪽 세로선이 있으면 표,
     아니면 본문
제외: excluded_regions.csv의 image·broken·example_box 영역이 표 면적의 tables.excluded_overlap_ratio 이상을 덮으면
다루지 않는다. 임계값은 config/params.yaml (tables, geometry), 폰트·박스 라벨은 config/profiles/<프로필>.yaml.

선 모양 (표 bbox 안의 선분, 1week-rag load_page_geometry 기준. 덤프 때 쪽별 파일에 저장한 선분을 읽는다):
  n_h = 표 폭 h_line_min_width_ratio 이상을 덮는 가로선 위치 수,
  n_vi = 표 높이 v_line_min_height_ratio 이상을 덮고 양쪽에 글자 줄이 있는 안쪽 세로선 위치 수,
  rows = 표 안 글자 줄의 행 수 (top ± row_tol_pt로 묶음, 라벨 열이 있으면 그 오른쪽 줄만),
  ruled = 이웃한 글자 행 사이를 가로선이 지나가는 곳의 수
  (d) 왼쪽 라벨 열 (채움 사각형 + 세로 구분, boxes.find_separator)이 있고 그 오른쪽에 안쪽 세로선이 없음
  (a) n_vi ≥ 1이고 ruled ≥ min(ruled_gaps_min, rows - 1) (행 사이에 가로선이 여러 번 지나감, 칸 안 여러 줄은 상관없음)
  (b) n_vi ≥ 1이고 그보다 적음 (머리 행 아래 선과 열 구분선만)
  (c) 안쪽 세로선이 없음 (① 표에서만 나올 수 있다)
  보정: ① 표이고 pdfplumber 격자 행이 tables.grid_rows_for_grid_shape 이상이면 (b)여도 (a) (shape_by_lines에 원래 값).
  (c)는 칸에 이미지를 채운 표라 그대로 둔다.
머리 행 채움: 표 위쪽에서 시작해 폭 header_fill_min_width_ratio 이상·높이 header_fill_max_height_ratio 이하인
채움 사각형 (흰색 제외)이 있으면 True.

출력: secure/tables/table_regions.jsonl (원문 없음, 영역·모양·수치)
확인용 출력 (--review, parsing/review/tables_classify.py): results/parsing/tables_classify.md (집계),
      review/wireframe/*.png (선·채움·줄 상자만, 글자 없음), review/tables_shapes.md (예시 표의 구조 수치)
실행 (requirements.txt 환경): python parsing/tables_classify.py
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boxes import _union_len, find_separator  # noqa: E402
from evalcore import area, center_in, chars_of, inter, lines_of, page_geometry, page_objects, regions_of  # noqa: E402
from config import P, box_kinds_not_table, fonts_of  # noqa: E402
from safeio import RESULTS, SECURE, out, review_mode, secure_path, setup  # noqa: E402
from samples import INCLUDED_PAGES, RANDOM15, SAMPLE45, zone_of  # noqa: E402
from tables_extract import invisible_segment_ids  # noqa: E402

BOX_LABEL_KINDS = box_kinds_not_table()
EXCL_FOR_TABLE = ("image", "broken", "example_box")
TITLE_BAND_FONTS = set(fonts_of("title_band"))
TABLE_DIR = SECURE / "tables"


def load_excluded() -> dict[int, list[list[float]]]:
    ex: dict[int, list[list[float]]] = defaultdict(list)
    with open(RESULTS / "parsing" / "excluded_regions.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["reason"] in EXCL_FOR_TABLE:
                ex[int(r["page"])].append([float(r["x0"]), float(r["top"]), float(r["x1"]), float(r["bottom"])])
    return ex


def load_boxes() -> dict[str, dict]:
    path = SECURE / "lines" / "boxes.json"
    return {b["region_id"]: b for b in json.loads(path.read_text(encoding="utf-8"))}


def excluded_frac(bbox, exs) -> float:
    a = area(bbox)
    return max((inter(bbox, e) / a for e in exs), default=0.0) if a else 0.0


def cluster(values: list[float], tol: float) -> list[float]:
    out_: list[list[float]] = []
    for v in sorted(values):
        if out_ and v - out_[-1][-1] <= tol:
            out_[-1].append(v)
        else:
            out_.append([v])
    return [sum(g) / len(g) for g in out_]


def visible_segments(geom, bbox, objs) -> list:
    """영역에 걸친 선분 중 보이지 않는 채움 사각형 테두리 (같은 색 사각형을 안쪽에 겹쳐 그린 칸)를 뺀 쪽 선분 목록.
    격자 추출 (tables_extract.fix_region_lines)과 같은 기준. 빼지 않으면 머리 행 경계·행 경계가 안쪽 사각형 변에 잡힌다."""
    x0, top, x1, bottom = bbox
    ids = [i for i, s in enumerate(geom.segments)
           if (s.orient == "h" and top - 2 <= s.pos <= bottom + 2 and s.end > x0 and s.start < x1)
           or (s.orient == "v" and x0 - 2 <= s.pos <= x1 + 2 and s.end > top and s.start < bottom)]
    inv, _ = invisible_segment_ids(geom, SimpleNamespace(bbox=bbox, segment_ids=ids), objs)
    drop = set(inv)
    return [s for i, s in enumerate(geom.segments) if i not in drop]


def shape_metrics(bbox, segments, lines_in, page, sep) -> dict:
    x0, top, x1, bottom = bbox
    w, h = x1 - x0, bottom - top
    ctol, touch = P("tables.line_cluster_tol_pt"), P("geometry.touch_tol_pt")
    margin, edge = P("geometry.inner_margin_pt"), P("geometry.left_edge_tol_pt")
    hs = [s.pos for s in segments if s.orient == "h" and top - ctol <= s.pos <= bottom + ctol
          and min(s.end, x1) - max(s.start, x0) >= P("tables.h_line_min_width_ratio") * w]
    vs = [s for s in segments if s.orient == "v" and x0 - ctol <= s.pos <= x1 + ctol]
    vpos: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for s in vs:
        a, b = max(s.start, top), min(s.end, bottom)
        if b > a:  # 표 높이 범위와 겹치는 부분만 (같은 쪽 다른 표의 선 제외)
            vpos[round(s.pos)].append((a, b))
    v_full = [x for x, spans in vpos.items() if _union_len(spans) >= P("tables.v_line_min_height_ratio") * h]
    # 안쪽 세로선 = 열 구분선: 선 왼쪽과 오른쪽에 모두 글자 줄이 있어야 한다 (이중 테두리의 안쪽 변은 세지 않음)
    v_in = cluster([x for x in v_full if x0 + margin < x < x1 - margin
                    and any(d["x0"] < x - touch for d in lines_in) and any(d["x1"] > x + touch for d in lines_in)], ctol)
    n_h = len(cluster(hs, ctol))
    # 글자 행: top ± row_tol_pt로 묶은 줄 묶음 (top, bottom). 이웃한 행 사이를 가로선이 지나가면 "구분된 행 사이"
    row_spans: list[list[float]] = []
    # 라벨 열만 차지한 줄은 행 경계에 걸쳐 있어 뺀다
    content = [d for d in lines_in if sep is None or d["x1"] > sep + P("tables.label_col_content_margin_pt")]
    for d in sorted(content, key=lambda d: d["top"]):
        if row_spans and d["top"] - row_spans[-1][0] <= P("tables.row_tol_pt"):
            row_spans[-1][1] = max(row_spans[-1][1], d["bottom"])
        else:
            row_spans.append([d["top"], d["bottom"]])
    rows = len(row_spans)
    ruled = sum(1 for (t1, b1), (t2, _) in zip(row_spans, row_spans[1:])
                if any(b1 - touch <= y <= t2 + touch for y in hs))
    v_right = [x for x in v_in if sep is not None and x > sep + margin]
    if sep is not None and not v_right:
        shape = "d"
    elif v_in and ruled >= min(P("tables.ruled_gaps_min"), rows - 1):
        shape = "a"
    elif v_in:
        shape = "b"
    else:
        shape = "c"
    header_fill = False
    for o in page.rects:
        if not o.get("fill"):
            continue
        col = o.get("non_stroking_color")
        if col in ((1,), (1, 1, 1), [1], [1, 1, 1], 1, (0, 0, 0, 0), [0, 0, 0, 0]):  # 흰색·투명 채움은 머리 행 아님
            continue
        ox0, ox1, ot, ob = float(o["x0"]), float(o["x1"]), float(o["top"]), float(o["bottom"])
        if (abs(ot - top) <= P("tables.header_fill_top_tol_pt") and (ox1 - ox0) >= P("tables.header_fill_min_width_ratio") * w
                and (ob - ot) <= P("tables.header_fill_max_height_ratio") * h and ox0 >= x0 - edge and ox1 <= x1 + edge):
            header_fill = True
            break
    return {"n_h": n_h, "n_v_inner": len(v_in), "rows_text": rows, "ruled_gaps": ruled, "sep_x": sep, "shape": shape,
            "header_fill": header_fill, "v_in_x": [round(x, 2) for x in v_in],
            "h_y": [round(y, 2) for y in cluster(hs, ctol)]}


def main() -> int:
    setup("tables_classify")
    excl = load_excluded()
    boxes = load_boxes()
    s45, r15 = set(SAMPLE45), set(RANDOM15)
    tables, skipped = [], Counter()
    for p in INCLUDED_PAGES:
        zone, _ = zone_of(p)
        regs = regions_of(p)
        chars = chars_of(p)
        lines = [d for d in lines_of(p) if not d["is_page_number"]]
        geom, page = None, None
        n = 0
        for r in regs:
            idx = [i for i, c in enumerate(chars) if c["region_id"] == r["region_id"] and c["zone"] in ("table", "box")]
            if not idx:
                continue
            if excluded_frac(r["bbox"], excl.get(p, [])) >= P("tables.excluded_overlap_ratio"):
                skipped["excluded_overlap"] += 1
                continue
            if geom is None:
                geom, page = page_geometry(p), page_objects(p)  # 덤프에 저장한 선·사각형 (PDF를 다시 열지 않음)
            lines_in = [d for d in lines if center_in({"x0": d["x0"], "x1": d["x1"], "top": d["top"], "bottom": d["bottom"]},
                                                      r["bbox"], P("tables.lines_in_tol_pt"))]
            m = shape_metrics(r["bbox"], visible_segments(geom, r["bbox"], page), lines_in, page, find_separator(page, r["bbox"]))
            band = any(d["region_id"] == r["region_id"] and d["font_key"] in TITLE_BAND_FONTS for d in lines)
            passed = r["kind"] == "table" and r["grid_ok"] and r["char_ok"]
            boxed = boxes.get(r["region_id"], {}).get("label_kind") in BOX_LABEL_KINDS
            # 1행짜리 상자는 표 아님
            geo_table = (m["sep_x"] is not None or m["n_v_inner"] >= 1) and m["rows_text"] >= P("tables.geo_table_min_rows")
            if band:
                decided, step = "title_band", "band"
            elif boxed:  # 박스 라벨이 검사 통과보다 먼저: 격자가 있어도 라벨 열이 박스 라벨이면 박스 (용어 해설 등)
                decided, step = "box", "2"
            elif passed:
                decided, step = "table", "1"
            else:
                decided, step = ("table" if geo_table else "body"), "3"
            rec = {"bbox": r["bbox"], "source": r["region_id"], "kind": r["kind"], "grid": r["shape"], "page": p, "zone": zone,
                   "decided": decided, "step": step, "n_chars": len(idx), **m}
            rec["passed"] = passed
            if decided == "table" and passed and rec["shape"] == "b" \
                    and int(r["shape"].split("x")[0]) >= P("tables.grid_rows_for_grid_shape"):
                # 격자 검사를 통과했고 격자 행이 충분하면 칸마다 테두리가 있는 표 (칸 배경 사각형 사이 틈으로 나뉜 빽빽한 표 등)
                rec["shape_by_lines"], rec["shape"] = rec["shape"], "a"
            if decided == "table":
                rec["table_id"] = f"T{p:03d}_{n}"
                n += 1
            tables.append(rec)
        if page is not None:
            page.flush_cache()
    with open(secure_path(TABLE_DIR / "table_regions.jsonl"), "w", encoding="utf-8") as f:
        for t in tables:
            f.write(json.dumps({**t, "set": "sample45" if t["page"] in s45 else ("random15" if t["page"] in r15 else "full")},
                               ensure_ascii=False) + "\n")
    if review_mode():
        from review.tables_classify import pick_examples, write_report, write_wireframes
        write_report(tables, skipped)
        examples = pick_examples([t for t in tables if t["decided"] in ("table", "title_band")])
        write_wireframes(examples, "tables_shapes.md", "표 모양 예시의 구조 수치 (와이어프레임과 함께 보기)")
    tt = [t for t in tables if t["decided"] == "table"]
    out("done", tables=len(tt), shapes=dict(Counter(t["shape"] for t in tt)), steps=dict(Counter(t["step"] for t in tt)),
        title_bands=sum(t["decided"] == "title_band" for t in tables), boxes=sum(t["decided"] == "box" for t in tables),
        body=sum(t["decided"] == "body" for t in tables), skipped=dict(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
