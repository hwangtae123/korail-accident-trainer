"""박스 블록 확인용 출력: 리포트 (results/parsing/box_blocks_report.md), 구조 수치 (review/), 블록·용어집 발췌 (secure/review/).

box_blocks.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter

from pdf_lines import md_table
from safeio import RESULTS, result_path, review_write, secure_review_write
from samples import RANDOM15


CHECK_TEXT = {"term_line_not_bold": "굵지 않은 용어 줄", "long_definition": "긴 정의 (용어 두 개가 붙었을 수 있음)"}


def write_report(blocks: list[dict], terms: list[dict], cands: Counter) -> None:
    kinds = Counter(b["box_kind"] for b in blocks)
    rows = [["박스 블록", len(blocks)]] + [[f"  {k}", v] for k, v in kinds.most_common()]
    rows += [["쪽 넘김 후보 (쪽 맨 위 박스 + 앞 쪽 마지막이 박스)", cands["page_top_after_box"]],
             ["  이어 붙임 (종류 같고 이어지는 쪽에 라벨 글자 없음)", cands["merged"]],
             ["  안 붙임: 종류 다름", cands["not_merged_kind_differs"]],
             ["  안 붙임: 이어지는 쪽에 라벨 글자 있음", cands["not_merged_has_label"]],
             ["라벨 열 없는 박스 (첫 줄이 라벨)", sum(b["label_source"] == "first_line" for b in blocks)],
             ["예시 범위가 있는 블록", sum("example_box" in b["excluded_lines"] for b in blocks)],
             ["예시 (계산식) 줄을 남긴 블록", sum(any(d.get("example") for d in b["content_lines"]) for b in blocks)],
             ["  남긴 예시 줄", sum(1 for b in blocks for d in b["content_lines"] if d.get("example"))],
             ["쪽 넘김으로 앞 블록에 이은 영역 (라벨 글자 없음)", sum(1 for b in blocks for _ in b["region_ids"][1:])],
             ["제외 줄 (예시)", sum(b["excluded_lines"].get("example_box", 0) for b in blocks)],
             ["제외 줄 (그 밖)", sum(v for b in blocks for k, v in b["excluded_lines"].items() if k != "example_box")],
             ["표 분류가 건너뛴 영역에서 만든 블록 (예시 앞 내용)", sum(b["from_skipped_region"] for b in blocks)],
             ["  예시뿐이라 블록 안 만든 박스 라벨 영역", cands["skipped_example_only"]],
             ["내용 글자가 없는 블록", sum(not b["text"] for b in blocks)],
             ["parent_hint 없음 (앞에 조 제목 없음)", sum(b["parent_hint"] is None for b in blocks)],
             ["용어집 항목", len(terms)],
             ["  용어 해설 블록 중 용어 0개", sum(b["box_kind"] == "box_terms" and not b["n_terms"] for b in blocks)],
             ["  꺾쇠 줄인데 짝 안 된 것", sum(max(0, b.get("unpaired_markers", 0)) for b in blocks)],
             ["  정의가 빈 용어", sum(not t["definition"] for t in terms)],
             ["  여러 쪽에 걸친 정의", sum(len(t["pages"]) > 1 for t in terms)],
             ["  같은 용어가 여러 블록에 (특약마다 반복)", sum(v > 1 for v in Counter(t["term"] for t in terms).values())],
             ["확인 필요 용어 해설 블록 (굵지 않은 용어 줄 / 긴 정의)", sum(bool(b.get("check")) for b in blocks)]]
    parts = ["# 3단계 박스 블록 리포트 (수치만)", "",
             "대상: 표 분류에서 박스로 정한 영역. 줄은 라벨 열 / 내용 열마다 묶음. 설명 박스 안 예시 (계산식)는 남기고 example 표시, 그 밖 예시는 제외.",
             "parent는 4단계에서 연결 (지금은 바로 앞 조 제목 줄을 parent_hint로).", "", md_table(["항목", "값"], rows), ""]
    result_path(RESULTS / "parsing" / "box_blocks_report.md").write_text("\n".join(parts), encoding="utf-8")


def write_structure(blocks: list[dict]) -> None:
    """review/ (구조 수치만): 종류별 블록 수, 줄 수 분포, 이어 붙인 블록."""
    rows = ["# 박스 블록 구조 (수치만)", "", "| 종류 | 블록 | 라벨 줄 (중앙값) | 내용 줄 (중앙값) | 여러 쪽 | 예시 제외 있음 |", "|---|---|---|---|---|---|"]
    for k in sorted({b["box_kind"] for b in blocks}):
        sel = [b for b in blocks if b["box_kind"] == k]
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0  # noqa: E731
        rows.append(f"| {k} | {len(sel)} | {med([len(b['label_lines']) for b in sel])} | {med([len(b['content_lines']) for b in sel])} | "
                    f"{sum(len(b['pages']) > 1 for b in sel)} | {sum('example_box' in b['excluded_lines'] for b in sel)} |")
    rows += ["", "## 쪽 넘김으로 이은 블록", "", "| block_id | 종류 | 쪽 | 쪽별 영역 높이 |", "|---|---|---|---|"]
    for b in blocks:
        if len(b["pages"]) > 1 and b["page"] not in RANDOM15:
            rows.append(f"| {b['block_id']} | {b['box_kind']} | {','.join(map(str, b['pages']))} | "
                        f"{', '.join(str(round(x[3] - x[1])) for x in b['bboxes'])} |")
    review_write("box_blocks_structure.md", rows, "박스 블록 종류별 수와 쪽 넘김 이음", {b["page"] for b in blocks if len(b["pages"]) > 1 and b["page"] not in RANDOM15})


def write_user_check(blocks: list[dict], terms: list[dict]) -> None:
    """사람 확인용 (원문, secure/review). 무작위 15쪽은 넣지 않는다."""
    pick, seen = [], Counter()
    for b in blocks:  # 종류마다 앞에서 4개 + 여러 쪽 블록 + 예시 제외 있는 블록 2개
        if b["page"] in RANDOM15:
            continue
        key = b["box_kind"]
        if b.get("check") or seen[key] < 4 or (len(b["pages"]) > 1 and seen["multi"] < 4) or ("example_box" in b["excluded_lines"] and seen["ex"] < 2):
            pick.append(b)
            seen[key] += 1
            seen["multi"] += len(b["pages"]) > 1
            seen["ex"] += "example_box" in b["excluded_lines"]
    rows = ["# 박스 블록 확인 (사람 확인용)", "", "줄 앞 [제외:이유]는 블록 글자에서 뺀 줄.", ""]
    for b in pick:
        rows += [f"## {b['block_id']} ({b['box_kind']}, 쪽 {', '.join(map(str, b['pages']))}, 라벨 출처 {b['label_source']})"
                 + (f" — 확인 필요: {', '.join(CHECK_TEXT[c] for c in b['check'])}" if b.get("check") else ""), "",
                 f"- 라벨: {b['label'] or '(없음)'}",
                 f"- parent_hint: {b['parent_hint']['text'] + ' (쪽 ' + str(b['parent_hint']['page']) + ')' if b['parent_hint'] else '(없음)'}",
                 "- 내용 줄:"]
        rows += [f"  - {'[제외:' + d['excluded'] + '] ' if d['excluded'] else ''}{d['text']}" for d in b["content_lines"]]
        rows += ["", f"- 블록 글자: {b['text']}", ""]
    secure_review_write("box_blocks.md", rows)
    rows = ["# 용어집 (사람 확인용)", "", "| 용어 | 정의 | 쪽 | 소속 조항 (임시: 바로 앞 조 제목) |", "|---|---|---|---|"]
    rows += [f"| {t['term'].replace('|', '/')} | {t['definition'].replace('|', '/')} | {','.join(map(str, t['pages']))} | "
             f"{t['parent_hint']['text'].replace('|', '/') if t['parent_hint'] else '-'} |" for t in terms if t["page"] not in RANDOM15]
    secure_review_write("glossary.md", rows)
