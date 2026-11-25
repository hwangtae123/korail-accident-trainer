"""3단계: 박스 블록과 용어집.

대상: 표 분류에서 박스로 정한 영역 (secure/tables/table_regions.jsonl decided = box). 열 나누기·라벨 종류는 boxes.py 결과.
- 칸 단위 줄: 박스 글자를 라벨 열 / 내용 열로 나눈 뒤 열마다 줄로 묶는다 (pdf_lines 줄은 영역 단위라 같은 높이의 라벨 글자와
  내용 글자가 한 줄로 묶일 수 있다). 열 안에서는 pdf_lines 줄 (line_id)과 같다 (박스 전체를 열마다 다시 묶어 확인).
  라벨 열이 없는 박스 (label_source = first_line)는 내용 첫 줄이 라벨.
- 제외 표시: 줄 글자의 exclude.line_excluded_ratio 이상이 제외 영역 (excluded_regions.csv) 안이면 그 이유로 표시 (삭제 안 함).
  예시 박스 (example_box)는 블록 글자에서 뺀다.
- 쪽 넘김 이어 붙이기: 다음 쪽 첫 내용이 이 박스이고 (위에 본문 줄 없음), 앞 블록이 앞 포함 쪽의 마지막 내용이며 (아래 본문 줄 없음),
  박스 종류가 같고 이어지는 쪽 박스에 라벨 글자가 없으면 (라벨 열 채움 색으로만 종류를 앎) 한 블록으로 잇는다.
- parent: 블록마다 읽기 순서 위치 (쪽, top)와 바로 앞 조 제목 줄 (조 패턴 + 프로필 article_title 폰트)을 parent_hint로 남긴다.
  최종 parent 연결은 4단계 본문 트리에서 한다.
- 용어집: 용어 해설 블록 내용 줄에서 꺾쇠로 감싼 용어로 시작하는 줄 + 정의 (다음 꺾쇠 줄 전까지). 용어, 정의, 쪽, 소속 조항 (parent_hint).

출력: secure/boxes/box_blocks.jsonl, secure/boxes/glossary.jsonl (원문)
확인용 출력 (--review, parsing/review/box_blocks.py): results/parsing/box_blocks_report.md (수치만), review/box_blocks_structure.md (구조 수치),
      secure/review/box_blocks.md + secure/review/glossary.md (사람 확인용 원문 발췌)
실행 (requirements.txt 환경): python parsing/box_blocks.py
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boxes import CLOSE, OPEN  # noqa: E402
from config import P, box_kinds_not_table, font  # noqa: E402
from evalcore import LINES_DIR, chars_of  # noqa: E402
from pdf_lines import load_week1  # noqa: E402
from safeio import RESULTS, SECURE, out, review_mode, secure_path, setup  # noqa: E402
from samples import INCLUDED_PAGES  # noqa: E402

BOX_DIR = SECURE / "boxes"
ARTICLE_PATTERNS = ("art_n", "art_nm")
TERM_RE = re.compile(f"[{OPEN}]([^{CLOSE}]+)[{CLOSE}]\\s*(.*)")


def load_excluded() -> dict[int, list[tuple[str, list[float]]]]:
    ex: dict[int, list] = defaultdict(list)
    with open(RESULTS / "parsing" / "excluded_regions.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ex[int(r["page"])].append((r["reason"], [float(r[k]) for k in ("x0", "top", "x1", "bottom")]))
    return ex


def load_marked() -> dict[int, list[dict]]:
    res: dict[int, list[dict]] = defaultdict(list)
    with open(SECURE / "lines" / "lines_marked.jsonl", encoding="utf-8") as f:
        for s in f:
            d = json.loads(s)
            res[d["page"]].append(d)
    return res


def excl_reason(cs: list[dict], exs: list) -> str | None:
    vis = [c for c in cs if c["text"].strip()]
    if not vis:
        return None
    hits = Counter()
    for c in vis:
        cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
        r = next((reason for reason, (x0, t, x1, b) in exs if x0 <= cx <= x1 and t <= cy <= b), None)
        if r:
            hits[r] += 1
    if hits and sum(hits.values()) / len(vis) >= P("exclude.line_excluded_ratio"):
        return hits.most_common(1)[0][0]
    return None


def cell_lines(cs: list[dict], exs: list) -> list[dict]:
    """한 열 (칸)의 글자를 줄로 묶는다. 열 안에서는 pdf_lines 줄 (line_id)과 같다."""
    g: dict = defaultdict(list)
    for c in cs:
        g[c["line_id"]].append(c)
    res = []
    for lid, ls in g.items():
        ls.sort(key=lambda c: c["x0"])
        vis = [c for c in ls if c["text"].strip()]
        if not vis:
            continue
        res.append({"text": "".join(c["text"] for c in ls).strip(), "line_id": lid,
                    "x0": round(vis[0]["x0"], 2), "x1": round(max(c["x1"] for c in vis), 2),
                    "top": round(min(c["top"] for c in vis), 2), "bottom": round(max(c["bottom"] for c in vis), 2),
                    "bold": round(sum(c["bold"] for c in vis) / len(vis), 3), "excluded": excl_reason(ls, exs)})
    return sorted(res, key=lambda d: (d["top"], d["x0"]))


def body_above_below(page_lines: list[dict], rid: str, bbox) -> tuple[int, int]:
    ok = [d for d in page_lines if not d["is_page_number"] and not d["excluded"] and d["region_id"] != rid]
    return sum(d["bottom"] <= bbox[1] + 1 for d in ok), sum(d["top"] >= bbox[3] - 1 for d in ok)


def article_lines(marked: dict[int, list[dict]]) -> list[tuple[int, float, dict]]:
    """조 제목 줄 (읽기 순서). 조 패턴으로 시작하고 프로필 article_title 폰트인 본문 줄."""
    res = []
    for p in INCLUDED_PAGES:
        for d in marked.get(p, []):
            if d["zone"] == "body" and not d["excluded"] and d["pattern"] in ARTICLE_PATTERNS and d["font_key"] == font("article_title"):
                res.append((p, d["top"], d))
    return sorted(res, key=lambda x: (x[0], x[1]))


def parent_hint(arts: list, page: int, top: float) -> dict | None:
    prev = [a for a in arts if (a[0], a[1]) < (page, top)]
    if not prev:
        return None
    p, _, d = prev[-1]
    return {"page": p, "line_id": d["line_id"], "pattern": d["pattern"], "text": d["text"].strip()}


def glossary(block: dict, join: str) -> list[dict]:
    """용어 해설 블록 내용 줄에서 <용어> + 정의 쌍."""
    terms, cur = [], None
    for d in block["content_lines"]:
        if d["excluded"]:
            continue
        m = TERM_RE.match(d["text"])
        if m:
            if cur:
                terms.append(cur)
            cur = {"term": m.group(1).strip(), "definition": m.group(2).strip(), "page": d["page"], "pages": [d["page"]]}
        elif cur is not None:
            cur["definition"] = (cur["definition"] + join + d["text"]).strip()
            if d["page"] not in cur["pages"]:
                cur["pages"].append(d["page"])
    if cur:
        terms.append(cur)
    return terms


def main() -> int:
    setup("box_blocks")
    cfg = load_week1()[0]
    join = cfg.cell_line_join
    boxes = {b["region_id"]: b for b in json.loads((LINES_DIR / "boxes.json").read_text(encoding="utf-8"))}
    all_regs = [json.loads(s) for s in (SECURE / "tables" / "table_regions.jsonl").read_text(encoding="utf-8").splitlines()]
    classified = {r["source"] for r in all_regs}
    # 표 분류가 제외 영역과 많이 겹쳐 건너뛴 영역 (예시가 대부분인 박스 등)도 박스 라벨이 있으면 후보로 둔다.
    # 예시 줄은 제외로 표시되고, 남는 내용이 없으면 아래에서 블록을 만들지 않는다.
    inc = set(INCLUDED_PAGES)
    skipped = [{"page": b["page"], "source": rid, "bbox": b["bbox"], "skipped": True} for rid, b in boxes.items()
               if b["page"] in inc and rid not in classified and b["n_chars"] and b["label_kind"] in box_kinds_not_table()]
    regs = sorted([r for r in all_regs if r["decided"] == "box"] + skipped, key=lambda r: (r["page"], r["bbox"][1]))
    excl, marked = load_excluded(), load_marked()
    arts = article_lines(marked)
    blocks, n_by_page, n_skipped_empty = [], Counter(), 0
    for r in regs:
        p, rid, b = r["page"], r["source"], boxes[r["source"]]
        sep = b["sep_x"]
        cs = [c for c in chars_of(p, with_space=True) if c["region_id"] == rid]
        label_cs = [c for c in cs if sep is not None and (c["x0"] + c["x1"]) / 2 < sep]
        content_cs = [c for c in cs if sep is None or (c["x0"] + c["x1"]) / 2 >= sep]
        label, content = cell_lines(label_cs, excl[p]), cell_lines(content_cs, excl[p])
        if b.get("label_source") == "first_line" and content:  # 라벨 열이 없는 박스: 첫 줄이 라벨
            label, content = content[:1], content[1:]
        ex_top = b["example_range"][1] if b.get("example_range") else None
        for d in label + content:
            d["page"] = p
            # 설명 박스 안 예시 (계산식)는 남기되 예시 줄임을 표시 (제외된 예시는 excluded = example_box)
            d["example"] = ex_top is not None and d in content and d["top"] >= ex_top - 1 and not d["excluded"]
        above, below = body_above_below(marked[p], rid, r["bbox"])
        if r.get("skipped") and not any(not d["excluded"] for d in content):
            n_skipped_empty += 1
            continue
        blocks.append({"from_skipped_region": bool(r.get("skipped")),"block_id": f"X{p:03d}_{n_by_page[p]}", "type": "box", "box_kind": b["label_kind"],
                       "label": "".join(d["text"] for d in label), "label_source": b.get("label_source"),
                       "page": p, "pages": [p], "bboxes": [r["bbox"]], "region_ids": [rid], "sep_x": sep, "split": b["split"],
                       "label_lines": label, "content_lines": content, "body_above": above, "body_below": below,
                       "order_key": [p, round(r["bbox"][1], 2)], "parent_hint": parent_hint(arts, p, r["bbox"][1])})
        n_by_page[p] += 1

    # 쪽 넘김 이어 붙이기
    merged, firsts, cands = [], {}, Counter()
    for bl in blocks:
        firsts.setdefault(bl["page"], bl)
    inc = INCLUDED_PAGES
    for bl in blocks:
        prev_pages = [q for q in inc if q < bl["page"]]
        last = merged[-1] if merged else None
        if (last is not None and prev_pages and last["pages"][-1] == prev_pages[-1] and firsts[bl["page"]] is bl
                and bl["body_above"] == 0 and last["body_below"] == 0):
            cands["page_top_after_box"] += 1
            if bl["box_kind"] == last["box_kind"] and not bl["label"]:
                last["pages"].append(bl["page"])
                last["bboxes"].append(bl["bboxes"][0])
                last["region_ids"] += bl["region_ids"]
                last["content_lines"] += bl["content_lines"]
                last["label_lines"] += bl["label_lines"]
                last["merged_ids"] = last.get("merged_ids", []) + [bl["block_id"]]
                last["body_below"] = bl["body_below"]
                cands["merged"] += 1
                continue
            cands["not_merged_" + ("kind_differs" if bl["box_kind"] != last["box_kind"] else "has_label")] += 1
        merged.append(bl)

    terms = []
    for bl in merged:
        kept = [d for d in bl["content_lines"] if not d["excluded"]]
        bl["text"] = join.join(d["text"] for d in kept)
        bl["excluded_lines"] = dict(Counter(d["excluded"] for d in bl["content_lines"] if d["excluded"]))
        if bl["box_kind"] == "box_terms":
            gl = glossary(bl, join)
            bl["n_terms"] = len(gl)
            bl["unpaired_markers"] = sum(1 for d in bl["content_lines"] if not d["excluded"] and d["text"][:1] in OPEN) - len(gl)
            # 확인 필요: 용어 줄이 굵지 않음 (다른 모양의 박스일 수 있음), 정의가 김 (용어 두 개가 붙었을 수 있음)
            bl["check"] = ((["term_line_not_bold"] if any(TERM_RE.match(d["text"]) and d["bold"] < 0.5
                                                          for d in bl["content_lines"] if not d["excluded"]) else [])
                           + (["long_definition"] if any(len(t["definition"]) > P("box_blocks.long_definition_chars") for t in gl) else []))
            for t in gl:
                terms.append({**t, "block_id": bl["block_id"], "parent_hint": bl["parent_hint"]})

    BOX_DIR.mkdir(parents=True, exist_ok=True)
    with open(secure_path(BOX_DIR / "box_blocks.jsonl"), "w", encoding="utf-8") as f:
        for bl in merged:
            f.write(json.dumps(bl, ensure_ascii=False) + "\n")
    with open(secure_path(BOX_DIR / "glossary.jsonl"), "w", encoding="utf-8") as f:
        for t in terms:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    cands["skipped_example_only"] = n_skipped_empty
    if review_mode():
        from review.box_blocks import write_report, write_structure, write_user_check
        write_report(merged, terms, cands)
        write_structure(merged)
        write_user_check(merged, terms)
    out("done", blocks=len(merged), kinds=dict(Counter(b["box_kind"] for b in merged)), merge=dict(cands), terms=len(terms),
        empty_text=sum(not b["text"] for b in merged), no_parent_hint=sum(b["parent_hint"] is None for b in merged))
    return 0


if __name__ == "__main__":
    sys.exit(main())
