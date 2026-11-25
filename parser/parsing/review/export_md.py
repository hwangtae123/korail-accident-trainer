"""파싱 결과 전체를 읽기 순서의 Markdown 한 파일로 내보낸다 (사람 확인용, 원문 → secure/review/full_parse.md).

구조: 구역 (#) > 계약 (##, 제목 띠) > 편·별표 (###) > 관 (####) > 조 (#####) > 항목 (들여쓴 목록, 조 아래 단계마다 2칸).
표: Markdown 표 (머리 행 첫 줄이 열 이름, 나머지 머리 행은 굵게 첫 행들로, 병합 칸은 걸친 칸마다 같은 글자), 아래 주석은 목록.
박스: 인용 블록 (라벨 + 내용 줄, 제외 줄은 뺌). 용어 해설은 "용어: 정의" 목록.
예시 그림 (제외한 예시 상자 자리): "[예시 그림: 잘라 둔 그림 경로]" + 아래 주석 목록.
표·박스는 트리에 붙은 자리 (attach_order: 몇 번째 자식 뒤)에 넣는다. 제외 표시된 내용은 이미 트리·표·박스에 없다.

검증 (수치만 출력): 포함 줄 (제외·쪽번호 아님)의 한글 음절 수와 내보낸 글의 한글 음절 수를 종류별로 비교한다.
표는 병합 칸 글자를 칸마다 되풀이하므로 100%를 넘을 수 있다. 표·박스마다 비율이 95%보다 낮으면 목록에 남긴다
(격자 표는 추출 때 센 칸 글자 cell_hangul 기준).
출력: secure/review/full_parse.md, results/parsing/export_md_report.md (수치만)
실행 (requirements.txt 환경): python parsing/review/export_md.py (또는 python parsing/run.py --review)
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pdf_lines import md_table  # noqa: E402
from safeio import RESULTS, SECURE, out, result_path, secure_review_write, setup  # noqa: E402
from samples import INCLUDED_PAGES  # noqa: E402

HANGUL = re.compile("[가-힣]")
HEAD = {"zone": "#", "contract": "##", "pyeon": "###", "section": "###", "gwan": "####", "article": "#####"}


def hcount(s: str) -> int:
    return len(HANGUL.findall(s))


def cell(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


def table_md(t: dict) -> list[str]:
    n = max([t["n_cols"]] + [len(r) for r in t["header"] + t["rows"]] or [1])
    head = t["header"][0] if t["header"] else [f"col{k + 1}" for k in range(n)]
    head = list(head) + [""] * (n - len(head))
    rows = [f"| {' | '.join(cell(c) for c in head)} |", "|" + "---|" * n]
    for r in t["header"][1:]:
        r = list(r) + [""] * (n - len(r))
        rows.append(f"| {' | '.join(('**' + cell(c) + '**') if c else '' for c in r)} |")
    for r in t["rows"]:
        r = list(r) + [""] * (n - len(r))
        rows.append(f"| {' | '.join(cell(c) for c in r)} |")
    rows += [f"- {cell(x)}" for x in t["notes"]]
    return [f"<!-- table {t['table_id']} p{','.join(map(str, t['pages']))} shape {t['shape']} -->"] + rows


def box_md(b: dict, terms: list[dict]) -> list[str]:
    rows = [f"<!-- box {b['block_id']} p{','.join(map(str, b['pages']))} {b['box_kind']} -->"]
    label = cell(b["label"]) if b["label"] else ""
    if b["box_kind"] == "box_terms" and terms:
        rows.append(f"> **{label}**" if label else ">")
        rows += [f"> - **{cell(t['term'])}**: {cell(t['definition'])}" for t in terms]
    else:
        body = [cell(d["text"]) for d in b["content_lines"] if not d["excluded"]]
        rows.append(f"> **{label}** {body[0] if body else ''}" if label else f"> {body[0] if body else ''}")
        rows += [f"> {x}" for x in body[1:]]
    return rows


def main() -> int:
    setup("export_md")
    nodes = [json.loads(s) for s in (SECURE / "tree" / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {n["id"]: n for n in nodes}
    tables = {t["table_id"]: t for t in map(json.loads, (SECURE / "tables" / "tables.jsonl").read_text(encoding="utf-8").splitlines())}
    blocks = {b["block_id"]: b for b in map(json.loads, (SECURE / "boxes" / "box_blocks.jsonl").read_text(encoding="utf-8").splitlines())}
    figs = {f["id"]: f for f in map(json.loads, (SECURE / "figures" / "figures.jsonl").read_text(encoding="utf-8").splitlines())}
    gl: dict[str, list[dict]] = {}
    for g in map(json.loads, (SECURE / "boxes" / "glossary.jsonl").read_text(encoding="utf-8").splitlines()):
        gl.setdefault(g["block_id"], []).append(g)

    emitted = Counter()
    rows = ["# 파싱 결과 전체 (사람 확인용)", "",
            "읽기 순서. 제목: # 구역, ## 계약, ### 편·별표, #### 관, ##### 조. 항목은 들여쓴 목록. "
            "표·박스 앞 주석 줄에 id·쪽. 제외 표시된 내용 (쪽번호, 양식 코드, 이미지, 도식, 예시)은 없음.", ""]

    def art_depth(n):
        a = by.get(n["article_id"]) if n["article_id"] else None
        if a:
            return a["depth"]
        q = by.get(n["parent_id"])
        while q is not None and q["type"] not in HEAD:
            q = by.get(q["parent_id"])
        return q["depth"] if q else 0

    def attach(n, kind_id):
        kind, i = kind_id["kind"], kind_id["id"]
        if kind == "table":
            t = tables[i]
            emitted["table"] += sum(hcount(c) for r in t["header"] + t["rows"] for c in r) + sum(hcount(x) for x in t["notes"])
            return [""] + table_md(t) + [""]
        if kind == "figure":
            f = figs[i]
            emitted["figure_note"] += sum(hcount(x) for x in f["notes"])
            return ["", f"<!-- figure {i} p{f['page']} example -->", f"> [예시 그림: {f['image']}]"] + [f"- {cell(x)}" for x in f["notes"]] + [""]
        b = blocks[i]
        ts = gl.get(i, [])
        emitted["box"] += hcount(b["label"]) + (sum(hcount(t["term"]) + hcount(t["definition"]) for t in ts) if b["box_kind"] == "box_terms" and ts
                                                  else sum(hcount(d["text"]) for d in b["content_lines"] if not d["excluded"]))
        return [""] + box_md(b, ts) + [""]

    def render(n):
        out_ = []
        title = cell(n["title"] or "") if n["type"] != "zone" else n["title"]
        text = cell(n["text"])
        if n["type"] in HEAD:
            lab = f"[{cell(n['label'])}] " if n.get("label") else ""
            out_ += ["", f"{HEAD[n['type']]} {lab}{title}".rstrip() + (f"  <!-- p{n['page_start']} -->" if n["page_start"] else ""), ""]
            if n.get("label"):
                emitted["section_label"] += hcount(n["label"])
            if n["type"] != "zone":
                emitted["title"] += hcount(n["title"] or "")
            if text:
                out_.append(text)
                emitted["text"] += hcount(n["text"])
        else:
            ind = "  " * max(0, n["depth"] - art_depth(n) - 1)
            tag = {"note": "", "bold": "**", "para": ""}.get(n["type"], "")
            body = f"{title} {text}".strip()
            out_.append(f"{ind}- {tag}{body}{tag}")
            emitted["title" if n["title"] else "text"] += hcount(n["title"] or "")
            emitted["text"] += hcount(n["text"])
        order = sorted(n.get("attach_order", []), key=lambda a: a["after_children"])
        kids = n["children"]
        pos = 0
        for k, c in enumerate(kids + [None]):
            while pos < len(order) and order[pos]["after_children"] <= k:
                out_ += attach(n, order[pos])
                pos += 1
            if c is not None:
                out_ += render(by[c])
        return out_

    for n in nodes:
        if n["parent_id"] is None:
            rows += render(n)
    secure_review_write("full_parse.md", rows)

    # 검증: 포함 줄의 한글 음절 수 (종류별)
    inc = set(INCLUDED_PAGES)
    regs = [json.loads(s) for s in (SECURE / "tables" / "table_regions.jsonl").read_text(encoding="utf-8").splitlines()]
    band = {r["source"] for r in regs if r["decided"] == "title_band"}
    tsrc = {r["table_id"]: r["source"] for r in regs if r.get("table_id")}
    table_regions = {tsrc[i]: tid for tid, t in tables.items() for i in [tid] + t.get("merged_ids", [])}
    box_regions = {rid: b["block_id"] for b in blocks.values() for rid in b["region_ids"]}
    src = Counter()
    per = Counter()
    note_ids = {(t["pages"][-1], i) for t in tables.values() for i in t["note_line_ids"]}
    fig_note_ids = {(f["page"], i) for f in figs.values() for i in f["note_line_ids"]}
    for d in map(json.loads, (SECURE / "lines" / "lines_marked.jsonl").open(encoding="utf-8")):
        if d["page"] not in inc or d["is_page_number"] or d["excluded"]:
            continue
        h = hcount(d["text"])
        if d["region_id"] in band:
            src["title"] += h
        elif (d["page"], d["line_id"]) in fig_note_ids:
            src["figure_note"] += h
        elif (d["page"], d["line_id"]) in note_ids:
            src["table"] += h
        elif d["region_id"] in table_regions and d["zone"] != "note":
            src["table"] += h
            per[("table", table_regions[d["region_id"]])] += h
        elif d["region_id"] in box_regions and d["zone"] != "note":
            src["box"] += h
            per[("box", box_regions[d["region_id"]])] += h
        else:
            src["tree"] += h
    emitted_tree = emitted["text"] + emitted["title"] + emitted["section_label"]
    rows_r = [["본문 트리 (제목 띠·별표 라벨 포함)", src["tree"] + src["title"], emitted_tree],
              ["표 (병합 칸 되풀이로 100% 넘을 수 있음)", src["table"], emitted["table"]],
              ["박스", src["box"], emitted["box"]],
              ["예시 그림 아래 주석", src["figure_note"], emitted["figure_note"]]]
    low = []
    for (kind, i), h in per.items():
        if h == 0:
            continue
        if kind == "table":
            t = tables[i]
            if "cell_hangul" in t:  # 격자 표: 추출 때 센 칸 글자 (병합 칸 한 번, 쪽마다 되풀이한 머리 행 포함 = 원본과 같은 기준)
                e = t["cell_hangul"]
            else:  # 줄 정렬·라벨+내용 표: 병합 칸 되풀이 없음
                e = sum(hcount(c) for r in t["header"] + t["rows"] for c in r)
        else:
            b = blocks[i]
            ts = gl.get(i, [])
            e = hcount(b["label"]) + (sum(hcount(t["term"]) + hcount(t["definition"]) for t in ts) if b["box_kind"] == "box_terms" and ts
                                      else sum(hcount(d["text"]) for d in b["content_lines"] if not d["excluded"]))
        if e / h < 0.95:
            low.append([kind, i, h, e, f"{100 * e / h:.1f}%"])
    parts = ["# 전체 Markdown 내보내기 검증 (수치만)", "",
             "한글 음절 수: 포함 줄 (제외·쪽번호 아님) 대 내보낸 글. 파일: `secure/review/full_parse.md` (원문).", "",
             md_table(["종류", "원본", "내보냄", "비율"], [r + [f"{100 * r[2] / r[1]:.1f}%" if r[1] else "-"] for r in rows_r]), "",
             f"## 비율 95% 미만인 표·박스: {len(low)}개", "",
             "격자 표는 추출 때 센 칸 글자 (병합 칸 한 번) 기준, 그 밖 표는 행 글자 그대로. 표 아래 주석은 비교에서 뺌.", "",
             md_table(["종류", "id", "원본", "내보냄", "비율"], low) if low else "없음", ""]
    result_path(RESULTS / "parsing" / "export_md_report.md").write_text("\n".join(parts), encoding="utf-8")
    out("done", md_lines=len(rows), tree=f"{emitted_tree}/{src['tree'] + src['title']}", table=f"{emitted['table']}/{src['table']}",
        box=f"{emitted['box']}/{src['box']}", low=len(low))
    return 0


if __name__ == "__main__":
    sys.exit(main())
