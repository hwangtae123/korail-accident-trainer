"""1단계 제외 확인용 출력: 제외 집계 리포트 (results/parsing/exclusion_full_report.md), broken 영역 발췌 (secure/review/).

exclude.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter
from pathlib import Path

from evalcore import lines_of
from exclude import REASONS
from pdf_lines import md_table
from safeio import RESULTS, result_path, secure_review_write
from samples import FINAL_ZONES, RANDOM15, SAMPLE45


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.2f}%" if b else "-"


def write_review(pages, reg_n: Counter, chr_n: Counter, total: int, page_rows: list, zone_tot: Counter, zone_exc: dict,
                 codes: set, code_other: int, sample_max: float, high: list, broken_pages: Counter, all_ex: list) -> Path:
    s45, r15 = set(SAMPLE45), set(RANDOM15)
    parts = [f"# 제외 전체 판 (2차 1단계 1-3, 포함 {len(pages)}쪽, 집계만)", "",
             "정의는 `parsing/exclude.py` 머리말. 지우지 않고 표시만 한다.", "",
             "## 이유별", "",
             md_table(["이유", "영역 수", "제외 글자", "전체 대비"],
                      [[r, reg_n[r], chr_n[r], _pct(chr_n[r], total)] for r in REASONS]
                      + [["합계", sum(reg_n.values()), sum(chr_n.values()), _pct(sum(chr_n.values()), total)]]), "",
             f"- 전체 글자 (공백 제외) {total}.", ""]
    zones = []
    for a, b, z, inc in FINAL_ZONES:
        if inc and z not in zones:
            zones.append(z)
    parts += ["## 구역별", "",
              md_table(["구역", "쪽 수", "글자", "제외 글자", "비율"] + list(REASONS),
                       [[z, sum(1 for r in page_rows if r[4] == z), zone_tot[z], sum(zone_exc[z].values()),
                         _pct(sum(zone_exc[z].values()), zone_tot[z])] + [zone_exc[z][r] for r in REASONS] for z in zones]), ""]

    # 샘플과 비교해 처음 보는 유형
    parts += ["## 샘플과 비교해 처음 보는 유형", "",
              f"- 양식 코드 줄 (form_code): {len(codes)}줄, 쪽 위 SLIL/7인데 코드 모양이 아닌 줄 {code_other}.",
              f"- broken: {sum(broken_pages.values())}영역, {len(broken_pages)}쪽. "
              f"영역이 2개 이상인 쪽: {', '.join(f'p{p} {n}' for p, n in broken_pages.most_common() if n >= 2) or '-'}.",
              f"- 제외 비율이 샘플 45쪽 최대 ({100 * sample_max:.1f}%)보다 높은 쪽: {len(high)}쪽.", ""]
    if high:
        parts += [md_table(["page", "구역", "글자", "제외", "비율", "이유별", "샘플"],
                           [[p, z, n, e, f"{100 * e / n:.1f}%", ", ".join(f"{k} {v}" for k, v in rc.most_common()),
                             "sample45" if p in s45 else ("random15" if p in r15 else "-")]
                            for p, n, e, rc, z in high[:20]]), ""]

    # 확인용 발췌 (무작위 15쪽 제외, 200줄 이내)
    rows = ["# broken 영역 (1-3 전체, 무작위 15쪽 제외, 영역마다 줄 3개까지)", "", "| page | 영역 | 줄 |", "|---|---|---|"]
    bpages = set()
    for e in all_ex:
        if e["reason"] != "broken" or e["page"] in r15 or len(rows) >= 190:
            continue
        rid = e["source"].split(":")[0]
        ls = [d["text"].strip() for d in lines_of(e["page"]) if d["region_id"] == rid][:3]
        bpages.add(e["page"])
        rows.append(f"| {e['page']} | {e['source']} | {' / '.join(ls).replace('|', '/')} |")
    secure_review_write("broken_full.md", rows)
    path = result_path(RESULTS / "parsing" / "exclusion_full_report.md")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path
