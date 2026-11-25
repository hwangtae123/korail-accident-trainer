"""박스 분석 확인용 출력: 샘플 쪽 라벨 열·예시 줄 확인, 용어 쌍 발췌 (secure/review/).

boxes.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

import json
from collections import Counter

from boxes import is_example_start, is_example_strict
from evalcore import LINES_DIR, chars_of, lines_of
from safeio import out, secure_path, secure_review_write
from samples import SAMPLE45


def write_review(boxes: list[dict], review: list, terms_review: list) -> None:
    """확인용 (확인 모드에서만): 샘플 45쪽 예시 줄 모양 개수, 박스 라벨 열·예시 시작 줄과 용어 해설 쌍 발췌."""
    # 2단계의 "예시가 줄 중간에 있는 줄" (sample45) 모양 확인: 내용 열 부분만 보고 개수만 센다
    by_region = {b["region_id"]: b for b in boxes}
    checks = Counter()
    for p in SAMPLE45:
        page_chars = chars_of(p, with_space=True)
        for d in lines_of(p):
            if "box_example" not in d["box_pattern_any"] or d["box_pattern"] == "box_example":
                continue
            b = by_region.get(d["region_id"])
            sep = b["sep_x"] if b else None
            seg = [c for c in page_chars if c["line_id"] == d["line_id"] and c["region_id"] == d["region_id"]
                   and (sep is None or (c["x0"] + c["x1"]) / 2 >= sep)]
            seg.sort(key=lambda c: c["x0"])
            vis = [c for c in seg if c["text"].strip()]
            t = "".join(c["text"] for c in seg).strip()
            bold = bool(vis) and sum(c["bold"] for c in vis) / len(vis) > 0.5
            dd = {"text": t, "bold": 1.0 if bold else 0.0}
            checks["줄 수"] += 1
            checks["〈 (U+3008)로 시작"] += t.startswith("〈")
            checks["< (U+003C)로 시작"] += t.startswith("<")
            checks["〉 (U+3009)로 끝남"] += t.endswith("〉")
            checks["> (U+003E)로 끝남"] += t.endswith(">")
            checks["굵은 글자 > 50%"] += bold
            checks["예시 시작 줄 (꺾쇠 시작·끝, 예시 포함, 굵게)"] += is_example_start(dd)
            checks["그중 '예시' 바로 뒤에 닫는 꺾쇠"] += is_example_strict(dd)
    secure_path(LINES_DIR / "example_line_checks.json").write_text(json.dumps(dict(checks), ensure_ascii=False), encoding="utf-8")

    s45 = set(SAMPLE45)
    rows = ["# 박스 라벨 열 / 예시 시작 줄 (샘플 45쪽)", "",
            "| page | region | split | sep_x | 라벨 판정 | 라벨 열 글자 | 예시 시작 줄 |", "|---|---|---|---|---|---|---|"]
    for e, lt, ex in review:
        if e["page"] in s45:
            rows.append(f"| {e['page']} | {e['region_id']} | {e['split']} | {e['sep_x']} | {e['label_kind']} | "
                        f"{lt.replace('|', '/')} | {ex.replace('|', '/')} |")
    secure_review_write("box_columns.md", rows)
    rows = ["# 용어 해설 박스의 <용어> + 정의 쌍 (샘플 45쪽)", "", "| page | region | 용어 | 정의 |", "|---|---|---|---|"]
    rows += [f"| {p} | {rid} | {a.replace('|', '/')} | {b.replace('|', '/')} |" for p, rid, a, b in terms_review if p in s45]
    secure_review_write("terms_pairs.md", rows)
    out("example_line_checks", values=list(checks.values()))
