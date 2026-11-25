"""1단계 덤프 확인용 출력: 샘플 45쪽 기준선 리포트 (results/parsing/pdf_baseline.md), 박스 라벨 발췌.

pdf_lines.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter
from pathlib import Path
from statistics import median

from config import box_labels
from pdf_lines import _EX, md_table
from safeio import RESULTS, SECURE, out, result_path, secure_path
from samples import SAMPLE45


SAMPLE_PAGES = SAMPLE45  # 2단계 리포트 대상. 덤프는 ALL_PAGES (무작위 15쪽 포함)


PATTERN_LEGEND = {
    "pyeon": "제N편", "gwan": "제N관", "art_nm": "제N-M조", "art_n": "제N조", "circled": "①~⑳",
    "num_dot": "1.", "hangul_dot": "가.", "num_paren": "1)", "hangul_paren": "가)", "note_ju": "(주)",
    "paren_num": "(1), ⑴", "paren_hangul": "(가)", "bullet": "□ ■ ○ ● ◆ ◇ ▶ ▷", "note_ref": "※", "note_cju": "㈜", "digits_only": "숫자만", "none": "없음",
}


BOX_LEGEND = {**box_labels(), "box_exN": f"{_EX[0]}N)"}


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(int(q * (len(s) - 1) + 0.5), len(s) - 1)]


def write_report(all_lines: list[dict], pages: dict, regions: list[dict]) -> Path:
    body = [d for d in all_lines if not d["is_page_number"]]
    parts = ["# PDF 문자 기준선 (2단계, 샘플 45쪽, 집계만)", "",
             "pdfplumber 0.11.10, 1week-rag `_group_lines`·`split_regions`·`parse_table` 사용. "
             "줄은 영역(table / note / box / body)마다 따로 묶었다. 쪽번호 줄은 본문 집계에서 뺐다.", ""]

    parts += ["## 쪽별 줄 수", ""]
    rows = []
    for p in SAMPLE_PAGES:
        pl = [d for d in body if d["page"] == p]
        z = Counter(d["zone"] for d in pl)
        m = pages[p]
        rows.append([p, len(pl), z["body"], z["table"], z["note"], z["box"],
                     "Y" if m["page_number_removed"] else "N", m["rel_x_kind"], round(m["rel_x_base"], 1)])
    parts += [md_table(["page", "lines", "body", "table", "note", "box", "page_no", "rel_x 기준", "기준 x0"], rows), ""]
    pn = [m for m in pages.values() if m["page_number_removed"]]
    offs = [m["page_number_offset"] for m in pn]
    parts += [f"- 쪽번호 줄 제거: {len(pn)}/{len(pages)}쪽"
              + (f", 가운데에서 어긋난 정도 {min(offs):+.1f}~{max(offs):+.1f}pt" if offs else ""),
              f"- rel_x 기준 종류: {dict(Counter(m['rel_x_kind'] for m in pages.values()))}", ""]

    parts += ["## 폰트별 줄·글자 수 (줄의 주 폰트 / 크기 중앙값)", ""]
    fc = Counter(d["font_key"] for d in body)
    fch = Counter()
    for d in body:
        fch[d["font_key"]] += d["n_chars"]
    parts += [md_table(["font", "lines", "chars", "bold 줄 (bold_ratio>0.5)"],
                       [[k, n, fch[k], sum(1 for d in body if d["font_key"] == k and d["bold_ratio"] > 0.5)]
                        for k, n in fc.most_common()]), ""]

    parts += ["## 패턴별 줄 수와 폰트", ""]
    pc = Counter(d["pattern"] for d in body)
    rows = []
    for k, n in pc.most_common():
        fonts = Counter(d["font_key"] for d in body if d["pattern"] == k).most_common(3)
        zones = Counter(d["zone"] for d in body if d["pattern"] == k)
        rows.append([k, PATTERN_LEGEND[k], n, ", ".join(f"{f} {c}" for f, c in fonts),
                     ", ".join(f"{z} {c}" for z, c in zones.most_common())])
    parts += [md_table(["pattern", "모양", "lines", "상위 폰트", "영역"], rows), ""]

    parts += ["## 패턴별 rel_x 분포 (pt, 표 밖 줄만)", ""]
    rows = []
    for k, _ in pc.most_common():
        xs = [d["rel_x"] for d in body if d["pattern"] == k and d["zone"] != "table"]
        if xs:
            rows.append([k, len(xs), min(xs), pct(xs, 0.1), median(xs), pct(xs, 0.9), max(xs)])
    parts += [md_table(["pattern", "n", "min", "p10", "median", "p90", "max"], rows), ""]

    parts += ["## 박스 라벨 패턴 (줄 맨 앞)", ""]
    bc = Counter(d["box_pattern"] for d in body if d["box_pattern"])
    rows = []
    for k in BOX_LEGEND:
        sel = [d for d in body if d["box_pattern"] == k]
        anywhere = sum(k in d["box_pattern_any"] for d in body)
        rows.append([k, BOX_LEGEND[k], bc[k], anywhere, ", ".join(f"{z} {c}" for z, c in Counter(d["zone"] for d in sel).most_common()),
                     ", ".join(f"{f} {c}" for f, c in Counter(d["font_key"] for d in sel).most_common(2)),
                     ",".join(str(p) for p in sorted({d["page"] for d in sel}))])
    parts += [md_table(["pattern", "모양", "줄 맨 앞", "줄 안 어디든", "영역 (맨 앞)", "상위 폰트 (맨 앞)", "쪽 (맨 앞)"], rows),
              "", "- 여는 괄호류 `[ < 〈 【 (` 허용, 라벨 뒤에 한글이 바로 이어지면 낱말 일부로 보고 뺀다.", ""]

    parts += ["## pdfplumber 영역 (표 감지)", ""]
    tbl = [r for r in regions if r["kind"] == "table"]
    rows = [
        ["표 (행 또는 열 2개 이상)", len(tbl)],
        ["격자·글자 검사 모두 통과", sum(r["grid_ok"] and r["char_ok"] for r in tbl)],
        ["격자 검사 실패", sum(not r["grid_ok"] for r in tbl)],
        ["글자 배정 실패", sum(not r["char_ok"] for r in tbl)],
        ["1×1 상자 (box)", sum(r["kind"] == "box" for r in regions)],
    ]
    rows += [[f"3주차 모양 {k}", v] for k, v in Counter(r["week3_shape"] for r in tbl if r["week3_shape"]).items()]
    parts += [md_table(["구분", "개수"], rows), ""]
    fail_pages = sorted({r["page"] for r in tbl if not (r["grid_ok"] and r["char_ok"])})
    parts += [f"- 검사 실패 영역이 있는 쪽: {', '.join(map(str, fail_pages))}", ""]

    path = result_path(RESULTS / "parsing" / "pdf_baseline.md")
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def write_box_label_review(all_lines: list[dict]) -> None:
    """사람 확인용 (원문 포함 → secure): 박스 라벨 모양이 줄 안 어디든 있는 줄."""
    hits = [d for d in all_lines if d["box_pattern_any"]]
    rows = ["# 박스 라벨 모양이 들어간 줄 (사람 확인용)", "",
            "확인할 것: 예시 / 설명 / [유의사항] / 용어 해설 / 예N) 박스 라벨이 실제로 어떤 모양인지 (줄 맨 앞이 아닌 경우 포함).", "",
            "| page | line_id | zone | region | font | x0 | top | 패턴 | text |", "|---|---|---|---|---|---|---|---|---|"]
    for d in hits:
        rows.append(f"| {d['page']} | {d['line_id']} | {d['zone']} | {d['region_id']} | {d['font_key']} | {d['x0']} | "
                    f"{d['top']} | {','.join(d['box_pattern_any'])} | {d['text'].strip().replace('|', '/')} |")
    secure_path(SECURE / "review" / "box_labels.md").write_text("\n".join(rows), encoding="utf-8")
    for k in BOX_LEGEND:
        sel = [d for d in hits if k in d["box_pattern_any"]]
        if sel:
            out("box_label_any", pattern=k, lines=len(sel), pages=sorted({d["page"] for d in sel}),
                zones=dict(Counter(d["zone"] for d in sel)), fonts=dict(Counter(d["font_key"] for d in sel)))
