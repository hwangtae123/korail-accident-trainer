"""D: 박스 내부를 pdfplumber 좌표로 라벨 열 / 내용 열로 나누고, 라벨·용어 해설 쌍·예시 범위를 찾는다.

대상: 샘플 60쪽과 포함 쪽의 pdfplumber 영역 중 글자 있는 것 전부 (검사 통과 표 포함: 라벨 열이 박스 라벨이면 표가 아니라
박스). 라벨 열 채움 색 (label_fill)도 기록한다.
열 나누기 (샘플 박스 측정으로 정한 규칙, 임계값은 config/params.yaml box_columns·geometry):
  1) line: 박스 높이 sep_cover_ratio 이상을 덮는 세로 구분 객체 (선·얇은 사각형, 색 무관, 흰색 포함)가 있고,
     박스 왼쪽 끝에서 시작해 그 x (± sep_fill_tol_pt)에서 끝나는 채움 사각형이 박스 높이 label_fill_cover_ratio 이상을 덮는다.
  2) gap: 1)이 없을 때, 박스 왼쪽 gap_max_x_ratio 안에서 시작하는 폭 gap_min_pt 이상의 글자 없는 세로 띠가 있고,
     띠 왼쪽 글자가 gap_left_bold_ratio 이상 굵거나 박스 라벨 모양이다.
  3) none: 나누지 않음 (전부 내용 열). 첫 줄이 박스 라벨 모양이면 그 줄을 라벨로 본다 (보조 규칙).
라벨 = 라벨 열 글자를 줄 순서로 이은 것 (공백·괄호 제거) → 프로필 box_labels 단어 / other.
라벨 글자가 없으면 라벨 열 채움 색이 프로필 box_label_fills에 있는지 본다 (label_source = fill).
그래도 없으면 쪽 넘김 이어짐을 본다 (continue_boxes, label_source = continued).
예시 시작 = 내용 열 줄이 프로필 example.open 꺾쇠로 시작하고 close 꺾쇠로 끝나며 keyword를 포함하고 굵은 글자가
example_bold_ratio 넘는 줄. 범위 = 그 줄 top부터 박스 끝.
용어 해설 쌍 = 용어 해설 박스 내용 열에서 꺾쇠로 감싼 용어로 시작하는 줄 + 정의 (같은 줄 뒤나 다음 줄들, 다음 꺾쇠 전까지).

출력: secure/lines/boxes.json (원문 없음)
확인용 출력 (--review, parsing/review/boxes.py): secure/lines/example_line_checks.json (개수만),
      secure/review/box_columns.md, secure/review/terms_pairs.md (원문 발췌, 샘플 45쪽만).
실행 (requirements.txt 환경): python parsing/boxes.py
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evalcore import (LINES_DIR, chars_of, lines_of, page_objects,  # noqa: E402
                      regions_of)
from config import P, box_kinds_not_table, box_labels, font, profile  # noqa: E402
from pdf_lines import BOX_PATTERNS  # noqa: E402
from safeio import out, review_mode, secure_path, setup  # noqa: E402
from samples import ALL_PAGES, INCLUDED_PAGES  # noqa: E402

LABEL_KEYS = list(box_labels().items())  # 회사 스타일 프로필 box_labels (순서대로 비교)
_STRIP = re.compile(r"[\s\[\]<>〈〉【】()（）]")


def _union_len(spans: list[tuple[float, float]]) -> float:
    tot, end = 0.0, None
    for a, b in sorted(spans):
        if end is None or a > end:
            tot += b - a
            end = b
        elif b > end:
            tot += b - end
            end = b
    return tot


def find_separator(page, bbox) -> float | None:
    x0, top, x1, bottom = bbox
    h = bottom - top
    thin, touch = P("geometry.thin_object_max_pt"), P("geometry.touch_tol_pt")
    margin, left_tol = P("geometry.inner_margin_pt"), P("geometry.left_edge_tol_pt")
    verts: dict[float, list[tuple[float, float]]] = defaultdict(list)
    fills = []
    for kind, objs in (("line", page.lines), ("rect", page.rects)):
        for o in objs:
            ox0, ox1, ot, ob = float(o["x0"]), float(o["x1"]), float(o["top"]), float(o["bottom"])
            if ox1 < x0 - touch or ox0 > x1 + touch or ob < top - touch or ot > bottom + touch:
                continue
            cx = (ox0 + ox1) / 2
            if ox1 - ox0 <= thin and x0 + margin < cx < x1 - margin:
                key = round(cx)
                verts[key].append((max(ot, top), min(ob, bottom)))
            if kind == "rect" and o.get("fill") and ox1 - ox0 > thin and ox0 <= x0 + left_tol:
                fills.append((ox1, max(ot, top), min(ob, bottom)))
    cands = sorted(x for x, spans in verts.items() if _union_len(spans) >= P("box_columns.sep_cover_ratio") * h
                   and x - x0 <= P("box_columns.sep_max_x_ratio") * (x1 - x0))
    for x in cands:
        cover = _union_len([(t, b) for (r, t, b) in fills if abs(r - x) <= P("box_columns.sep_fill_tol_pt")])
        if cover >= P("box_columns.label_fill_cover_ratio") * h:
            return float(x)
    return None


def label_fill_color(page, bbox, sep: float) -> list[float] | None:
    """라벨 열 채움 사각형 (박스 왼쪽 끝에서 시작해 구분선 x에서 끝남) 중 가장 높은 것의 채움 색 (기록용)."""
    x0, top, x1, bottom = bbox
    best = None
    for o in page.rects:
        if not o.get("fill"):
            continue
        ox0, ox1 = float(o["x0"]), float(o["x1"])
        if ox0 <= x0 + P("geometry.left_edge_tol_pt") and abs(ox1 - sep) <= P("box_columns.sep_fill_tol_pt"):
            h = min(float(o["bottom"]), bottom) - max(float(o["top"]), top)
            if best is None or h > best[0]:
                best = (h, o.get("non_stroking_color"))
    if best is None or best[1] is None:
        return None
    c = best[1]
    return [round(float(v), 2) for v in (c if isinstance(c, (list, tuple)) else [c])]


def find_gap(chars: list[dict], bbox) -> float | None:
    x0, _, x1, _ = bbox
    spans = sorted((c["x0"], c["x1"]) for c in chars)
    end = None
    for a, b in spans:
        if end is not None and a - end >= P("box_columns.gap_min_pt") and end - x0 <= P("box_columns.gap_max_x_ratio") * (x1 - x0):
            left = [c for c in chars if c["x1"] <= end + 0.5]
            text = "".join(c["text"] for c in sorted(left, key=lambda c: (c["top"], c["x0"])))
            if sum(c["bold"] for c in left) / len(left) >= P("box_columns.gap_left_bold_ratio") \
                    or any(rx.match(text) for _, rx in BOX_PATTERNS):
                return (end + a) / 2
        end = b if end is None else max(end, b)
    return None


def label_kind(text: str) -> tuple[str | None, bool]:
    t = _STRIP.sub("", text)
    if not t:
        return None, False
    for kind, key in LABEL_KEYS:
        if t == key:
            return kind, True
    for kind, key in LABEL_KEYS:
        if key in t:
            return kind, False
    return "other", False


def col_lines(chars: list[dict]) -> list[dict]:
    """같은 PDF 줄 (line_id)의 글자끼리 묶어 줄로 만든다 (top 순, 줄 안 x0 순)."""
    g: dict = defaultdict(list)
    for c in chars:
        g[c["line_id"]].append(c)
    res = []
    for cs in g.values():
        cs.sort(key=lambda c: c["x0"])
        vis = [c for c in cs if c["text"].strip()]
        if not vis:
            continue
        res.append({"text": "".join(c["text"] for c in cs).strip(), "top": min(c["top"] for c in cs),
                    "bottom": max(c["bottom"] for c in cs), "x0": vis[0]["x0"],
                    "bold": sum(c["bold"] for c in vis) / len(vis), "line_id": cs[0]["line_id"]})
    return sorted(res, key=lambda d: (d["top"], d["x0"]))


# 예시 꺾쇠·키워드는 회사 스타일 프로필 example (이 회사 문서의 꺾쇠는 ASCII < >, 〈 〉도 같이 받는다)
OPEN, CLOSE, EX_KEY = profile()["example"]["open"], profile()["example"]["close"], profile()["example"]["keyword"]


def is_example_start(d: dict) -> bool:
    """꺾쇠로 시작하고 꺾쇠로 끝나며 예시 키워드를 포함하는 굵은 줄."""
    t = d["text"].strip()
    return bool(t) and t[0] in OPEN and t[-1] in CLOSE and EX_KEY in t and d["bold"] > P("box_columns.example_bold_ratio")


def is_example_strict(d: dict) -> bool:
    """좁은 모양: 키워드 바로 뒤가 닫는 꺾쇠로 끝남 (집계용)."""
    t = d["text"].strip()
    return is_example_start(d) and t[:-1].rstrip().endswith(EX_KEY)


def terms_pairs(content: list[dict]) -> list[tuple[str, str]]:
    pairs, cur = [], None
    for d in content:
        t = d["text"].strip()
        m = re.match(f"[{OPEN}]([^{CLOSE}]+)[{CLOSE}]\\s*(.*)", t)
        if m:
            if cur:
                pairs.append(cur)
            cur = [m.group(1).strip(), m.group(2).strip()]
        elif cur is not None:
            cur[1] = (cur[1] + " " + t).strip()
    if cur:
        pairs.append(cur)
    return [(a, b) for a, b in pairs if a and b]


def continue_boxes(entries: list[dict]) -> int:
    """쪽 넘김 이어짐: 라벨 열은 있는데 라벨 글자가 없는 영역이 쪽 맨 위 내용이고 (위에 본문 줄 없음), 앞 포함 쪽의 마지막 내용이
    박스이며 (아래 본문 줄 없음) 두 라벨 열 채움 색이 box_columns.continue_fill_tol 안에서 같으면, 앞 박스의 종류를 이어받는다
    (label_source = continued). 색만으로 정하지 않는 이유: 설명 박스와 거의 같은 색 (0.01 차이)을 쓰는 라벨+내용 표가 있다."""
    tol = P("box_columns.continue_fill_tol")
    kinds = box_kinds_not_table()
    by_page: dict[int, list[dict]] = defaultdict(list)
    for e in entries:
        if e["n_chars"]:
            by_page[e["page"]].append(e)

    def body(p):
        return [d for d in lines_of(p) if d["region_id"] is None and not d["is_page_number"]
                and not d["font_key"].startswith(font("form_code"))]

    inc, n = sorted(INCLUDED_PAGES), 0
    for q, p in zip(inc, inc[1:]):
        cands = [e for e in by_page[p] if e["split"] == "line" and e["label_kind"] is None and e.get("label_fill")]
        prev = [e for e in by_page[q] if e["label_kind"] in kinds and e.get("label_fill")]
        if not cands or not prev:
            continue
        last, e = max(prev, key=lambda x: x["bbox"][3]), min(cands, key=lambda x: x["bbox"][1])
        if any(d["top"] >= last["bbox"][3] - 1 for d in body(q)) or any(d["bottom"] <= e["bbox"][1] + 1 for d in body(p)):
            continue
        if len(last["label_fill"]) == len(e["label_fill"]) and all(abs(a - b) <= tol for a, b in zip(last["label_fill"], e["label_fill"])):
            e.update(label_kind=last["label_kind"], label_source="continued", continued_from=last["region_id"])
            n += 1
    return n


def main() -> int:
    setup("boxes")
    boxes, review, terms_review = [], [], []
    for p in sorted(set(ALL_PAGES) | set(INCLUDED_PAGES)):
        page = page_objects(p)  # 그리기 객체는 쪽별 파일에서 읽는다 (PDF를 다시 열지 않음)
        page_chars = chars_of(p, with_space=True)
        for r in regions_of(p):  # 검사 통과 표도 본다 (라벨 열이 박스 라벨이면 표가 아니라 박스)
            cs = [c for c in page_chars if c["region_id"] == r["region_id"] and c["zone"] in ("table", "box")]
            vis = [c for c in cs if c["text"].strip()]
            entry = {"page": p, "region_id": r["region_id"], "kind": r["kind"], "bbox": r["bbox"],
                     "n_chars": len(vis), "split": "none", "sep_x": None, "label_kind": None, "label_exact": False,
                     "label_len": 0, "label_lines": 0, "content_lines": 0, "terms_pairs": 0,
                     "example_start": False, "example_range": None}
            if not vis:
                boxes.append(entry)
                continue
            sep = find_separator(page, r["bbox"])
            split = "line" if sep is not None else None
            if sep is None:
                sep = find_gap(vis, r["bbox"])
                split = "gap" if sep is not None else "none"
            label_cs = [c for c in cs if sep is not None and (c["x0"] + c["x1"]) / 2 < sep]
            content_cs = [c for c in cs if sep is None or (c["x0"] + c["x1"]) / 2 >= sep]
            label_lines, content = col_lines(label_cs), col_lines(content_cs)
            label_text = "".join(d["text"] for d in label_lines)
            kind, exact = label_kind(label_text)
            label_source = "column" if label_lines else None
            if not label_lines and content and any(rx.match(content[0]["text"]) for k, rx in BOX_PATTERNS
                                                   if k in box_kinds_not_table()):
                # 열을 못 나눈 박스: 첫 줄이 설명 / 유의사항 / 용어 해설 모양이면 그 줄을 라벨로 본다 (보조 규칙)
                label_text = content[0]["text"]
                kind, exact = label_kind(label_text)
                label_source = "first_line"
            fill = label_fill_color(page, r["bbox"], sep) if split == "line" else None
            if kind is None and fill is not None:  # 라벨 글자가 없으면 라벨 열 채움 색으로 (프로필 box_label_fills)
                tol = profile()["box_label_fill_tol"]
                hit = next((f["kind"] for f in profile().get("box_label_fills", [])
                            if len(f["fill"]) == len(fill) and all(abs(a - b) <= tol for a, b in zip(f["fill"], fill))), None)
                if hit:
                    kind, label_source = hit, "fill"
            ex = next((d for d in content if is_example_start(d)), None)
            pairs = terms_pairs(content) if kind == "box_terms" else []
            entry.update(split=split, sep_x=sep, label_kind=kind, label_exact=exact, label_source=label_source,
                         passed_table=r["kind"] == "table" and r["grid_ok"] and r["char_ok"],
                         label_fill=fill,
                         label_len=len(_STRIP.sub("", label_text)), label_lines=len(label_lines),
                         content_lines=len(content), terms_pairs=len(pairs), example_start=ex is not None,
                         example_strict=ex is not None and is_example_strict(ex),
                         terms_unpaired_markers=sum(1 for d in content if d["text"][:1] in OPEN) - len(pairs)
                         if kind == "box_terms" else 0,
                         example_range=[r["bbox"][0], ex["top"], r["bbox"][2], r["bbox"][3]] if ex else None)
            boxes.append(entry)
            review.append((entry, label_text, ex["text"] if ex else ""))
            terms_review += [(p, r["region_id"], a, b) for a, b in pairs]

    n_continued = continue_boxes(boxes)
    secure_path(LINES_DIR / "boxes.json").write_text(json.dumps(boxes), encoding="utf-8")

    if review_mode():
        from review.boxes import write_review
        write_review(boxes, review, terms_review)

    withc = [b for b in boxes if b["n_chars"]]
    out("boxes", total=len(boxes), with_chars=len(withc), split=dict(Counter(b["split"] for b in withc)),
        label=dict(Counter(str(b["label_kind"]) for b in withc)),
        exact=sum(b["label_exact"] for b in withc), examples=sum(b["example_start"] for b in withc),
        terms_pairs=sum(b["terms_pairs"] for b in withc),
        continued=n_continued)
    return 0


if __name__ == "__main__":
    sys.exit(main())
