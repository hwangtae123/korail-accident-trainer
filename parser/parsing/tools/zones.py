"""2차 1단계 1-1: 쪽 단위 구역 후보 (구역 경계 확인 범위: 1~40, 60~70, 84~100, 700~746쪽).

쪽마다 수치 (글자 수, 제목 띠·편·관 폰트 줄 수, 편·관·조 줄 수, 래스터 이미지 수 등)를 내고,
아래 규칙을 위에서부터 적용해 구역 후보를 붙인다. 최종 구역은 config/docs/<doc_id>.yaml에서 가져와 page_zones.csv로 쓴다.
폰트 역할은 config/profiles/<프로필>.yaml, 임계값은 config/params.yaml zone_candidates.
  빈쪽 (글자 0) → 목차·간지 /
  글자 < divider_max_chars이고 제목 띠 폰트·divider_big_font_pt 이상 줄 → 목차·간지 /
  편 제목 폰트 편 줄 또는 조 제목 폰트 제N-M조 → 특약 / 관 제목 폰트 관 줄 또는 조 제목 폰트 제N조 → 주계약
  (장해분류표 후보가 나온 뒤면 장해분류표 이후) / small 폰트 글자 비율 ≥ disability_small_share (특약 쪽이 나온 뒤에만)
  → 장해분류표 / 그 밖 → 앞 쪽 후보를 잇는다 (처음은 앞단, 빈쪽·글자적음+큰제목으로 잡힌 간지 한 장은 잇지 않음).
주계약 1종·2종, 부록은 수치로 가를 수 없어 사람 확인에 맡긴다.

출력: results/parsing/page_zone_candidates.csv, results/parsing/zones.md (수치만), secure/review/zone_titles.md (원문 발췌)
실행 (requirements.txt 환경): python parsing/tools/zones.py
"""

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # parsing/ (공용 모듈)
from evalcore import chars_of, lines_of, pages_meta  # noqa: E402
from pdf_lines import md_table  # noqa: E402
from safeio import RESULTS, ROOT, Trusted, rel, out, result_path, secure_review_write, setup  # noqa: E402
from config import P, font, fonts_of  # noqa: E402
from samples import INCLUDED_PAGES, N_PAGES, ZONE_PAGES, zone_of  # noqa: E402

BAND_FONTS = fonts_of("title_band")
TITLE_FONTS = tuple(BAND_FONTS + [font("pyeon_title"), font("gwan_title")])


def page_stats(p: int) -> dict:
    meta = pages_meta()[p]
    lines = [d for d in lines_of(p) if not d["is_page_number"]]
    fk = Counter(d["font_key"] for d in lines)
    chars = chars_of(p)
    n = len(chars)
    small_name, small_size = font("small").split("/")

    def pat(name: str, role: str | None = None) -> int:
        return sum(1 for d in lines if d["pattern"] == name and (role is None or d["font_key"] == font(role)))

    return {
        "page": p, "n_chars": n, "n_lines": len(lines),
        "band_font_lines": sum(fk[f] for f in BAND_FONTS), "pyeon_font_lines": fk[font("pyeon_title")],
        "gwan_font_lines": fk[font("gwan_title")],
        "big_lines": sum(1 for d in lines if d["size"] >= P("zone_candidates.divider_big_font_pt")),
        "pyeon": pat("pyeon"), "pyeon_title": pat("pyeon", "pyeon_title"),
        "gwan": pat("gwan"), "gwan_title": pat("gwan", "gwan_title"),
        "art_n": pat("art_n"), "art_n_title": pat("art_n", "article_title"),
        "art_nm": pat("art_nm"), "art_nm_title": pat("art_nm", "article_title"),
        "small_share": round(sum(1 for c in chars if c["font"] == small_name and round(c["size"]) == float(small_size)) / n, 3)
        if n else 0.0,
        "raster_images": sum(1 for bb in meta["image_bboxes"]
                             if min(bb[2] - bb[0], bb[3] - bb[1]) >= P("exclude.raster_min_side_pt")),
        "page_number_rule": meta["page_number_removed"],
    }


def candidate(s: dict, prev: str | None, seen_rider: bool, seen_disability: bool) -> tuple[str, str]:
    if s["n_chars"] == 0:
        return "목차·간지", "빈쪽"
    if s["n_chars"] < P("zone_candidates.divider_max_chars") and (s["band_font_lines"] or s["big_lines"]):
        return "목차·간지", "글자적음+큰제목"
    if s["pyeon_title"] or s["art_nm_title"]:
        return "특약", "편/제N-M조 제목"
    if s["gwan_title"] or s["art_n_title"]:
        return ("장해분류표 이후" if seen_disability else "주계약"), "관/제N조 제목"
    if s["small_share"] >= P("zone_candidates.disability_small_share") and seen_rider:
        return "장해분류표", "small 폰트 비율"
    return (prev or "앞단"), "앞쪽 잇기"


def main() -> int:
    setup("zones")
    stats, carry = [], "앞단"
    for p in ZONE_PAGES:
        s = page_stats(p)
        cand, rule = candidate(s, carry, any(x["candidate"] == "특약" for x in stats),
                               any(x["candidate"] == "장해분류표" for x in stats))
        s.update(candidate=cand, rule=rule)
        stats.append(s)
        if rule not in ("빈쪽", "글자적음+큰제목"):  # 간지 한 장은 뒤 쪽으로 잇지 않는다
            carry = cand

    cols = list(stats[0].keys())
    with open(result_path(RESULTS / "parsing" / "page_zone_candidates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(stats)

    # 후보가 바뀌는 쪽 (경계 후보)
    changes = [s for i, s in enumerate(stats) if i == 0 or s["candidate"] != stats[i - 1]["candidate"]
               or s["page"] != stats[i - 1]["page"] + 1]
    show = ["page", "candidate", "rule", "n_chars", "band_font_lines", "pyeon_font_lines", "gwan_font_lines", "pyeon_title",
            "gwan_title", "art_n_title", "art_nm_title", "art_n", "small_share", "raster_images"]
    parts = ["# 구역 후보 (2차 1단계 1-1, 수치만)", "",
             "범위: 1~40, 60~70, 84~100, 700~746쪽. 규칙은 `parsing/zones.py` 머리말. 전체 쪽 수치는 "
             "`results/parsing/page_zone_candidates.csv`. 제목 줄 원문은 `secure/review/zone_titles.md`.", "",
             "## 구역 후보 구간", ""]
    runs, start = [], 0
    for i in range(1, len(stats) + 1):
        if i == len(stats) or stats[i]["candidate"] != stats[start]["candidate"] or stats[i]["page"] != stats[i - 1]["page"] + 1:
            runs.append([f"{stats[start]['page']}~{stats[i - 1]['page']}", stats[start]["candidate"], i - start,
                         ", ".join(f"{k} {v}" for k, v in Counter(s["rule"] for s in stats[start:i]).most_common())])
            start = i
    parts += [md_table(["쪽", "후보", "쪽 수", "근거 규칙"], runs), "",
              "## 쪽별 수치 (경계 근처: 후보가 바뀌는 쪽과 앞뒤 1쪽)", ""]
    near = sorted({s["page"] + d for s in changes for d in (-1, 0, 1)} & set(ZONE_PAGES))
    parts += [md_table(show, [[s[k] for k in show] for s in stats if s["page"] in near]), ""]
    path = result_path(RESULTS / "parsing" / "zones.md")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")

    # 사람 확인용: 제목 폰트 줄과 큰 글씨 줄, 후보가 바뀌는 쪽의 처음 3줄
    rows = ["# 구역 경계 확인용 제목 줄 (사람 확인용)", "",
            "확인할 것: 쪽마다 구역 (앞단 / 목차·간지 / 주계약 1종 / 주계약 2종 / 특약 / 장해분류표 / 장해분류표 이후 / 부록) 확정.", "",
            "| page | 후보 | 규칙 | 종류 | font | text |", "|---|---|---|---|---|---|"]
    by_page = {s["page"]: s for s in stats}
    change_pages = {s["page"] for s in changes}
    for p in ZONE_PAGES:
        s = by_page[p]
        ls = [d for d in lines_of(p) if not d["is_page_number"]]
        picked = [(d, "제목폰트") for d in ls if d["font_key"] in TITLE_FONTS or d["size"] >= 14]
        if p in change_pages:
            picked += [(d, "쪽 처음") for d in ls[:3] if (d, "제목폰트") not in picked]
        if not picked:
            rows.append(f"| {p} | {s['candidate']} | {s['rule']} | (제목 줄 없음) | | |")
        for d, kind in picked:
            rows.append(f"| {p} | {s['candidate']} | {s['rule']} | {kind} | {d['font_key']} | "
                        f"{d['text'].strip().replace('|', '/')} |")
    secure_review_write("zone_titles.md", rows)
    for r in runs:
        out("zone_run", pages=Trusted(r[0]), candidate=Trusted(r[1]), n=r[2])

    # 최종 구역 (samples.FINAL_ZONES) → page_zones.csv (전체 쪽)
    by_page = {s["page"]: s for s in stats}
    with open(result_path(RESULTS / "parsing" / "page_zones.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["page", "zone", "included", "basis"])
        for p in range(1, N_PAGES + 1):
            zone, inc = zone_of(p)
            s = by_page.get(p)
            basis = f"후보 {s['candidate']} ({s['rule']})" if s else "확인 범위 밖 (앞뒤 구역 이어짐)"
            w.writerow([p, zone, int(inc), basis])
    out("page_zones", pages=N_PAGES, included=len(INCLUDED_PAGES))
    out("done", report=Trusted(rel(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
