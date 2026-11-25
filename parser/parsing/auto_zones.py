"""자동 구역 (run.py의 zones 단계, 덤프 다음). 문서 설정의 구역이 임시 (zones_status: provisional)일 때만 돈다.

쪽마다 parsing/tools/zones.py의 구역 후보 규칙 (page_stats, candidate)을 전체 쪽에 적용하고, 같은 후보가 이어지는 쪽을
한 구역으로 묶는다. 제외: 앞단 (첫 편·관·조 제목 앞의 표지·안내·목차), 목차·간지 (글자 적고 큰 제목만 있는 쪽).
프로필 auto_zones에 따라 포함 구역의 이름이 다르다:
  insurance  주계약 / 특약 / 장해분류표 / 장해분류표 이후 (보험 약관 이름 그대로)
  generic    모두 "본문" (다른 문서. 기본값)
  report     장·절 번호 보고서 (report_zones): 목차 점선 (프로필 report.toc_leader) 줄이 3개 이상인 쪽은 목차·간지,
             첫 목차 쪽 앞 (표지·안내문)은 앞단, 나머지는 본문 (목차 바로 뒤 사고 요약·개요 쪽도 본문).
             목차 쪽이 없으면 첫 장 제목 ("Ⅰ. …", "1. …", "개요") 앞 쪽을 앞단으로.
tools/zones.py와 다른 점: 제목 폰트 편·관·조 줄이 있는 쪽은 글자가 적어도 간지 (글자적음+큰제목)로 보지 않는다.
부록, 중간의 목차 쪽 (글자가 많은 것)은 규칙으로 가를 수 없어 포함으로 남는다 → 문서 설정을 확인해 고친다.
포함 쪽이 하나도 없으면 (프로필 폰트가 이 문서와 맞지 않는 등) 전체 쪽을 포함으로 두고 경고를 낸다.
결과는 config/docs/<doc_id>.yaml의 zones에 쓰고 zones_status: auto로 바꾼다 (다른 줄은 그대로).
쪽 수치는 results/<doc_id>/parsing/auto_zones.csv.
실행 (requirements.txt 환경): PARSE_DOC=<doc_id> python parsing/auto_zones.py
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DOCS_DIR, doc, doc_id, profile  # noqa: E402
from docs import set_zones  # noqa: E402
from safeio import RESULTS, Trusted, out, result_path, setup  # noqa: E402

EXCLUDED = {"앞단", "목차·간지"}
FIRST_HEADING = re.compile(r"(?:[ⅠⅡ]\.?\s*\S|1\.\s+\S)")


def report_zones(n: int) -> tuple[list[list], list[dict]]:
    """보고서 구역: [[첫 쪽, 끝 쪽, 구역, 포함]], 쪽 수치."""
    from evalcore import lines_of

    rp = profile().get("report") or {}
    leader = re.compile(rp.get("toc_leader") or r"[·.…]{4,}")
    unnumbered = {re.sub(r"\s", "", w) for w in rp.get("unnumbered_headings") or []}

    def bare(t):  # 공백과 끝 괄호 ("개요(Synopsis)") 뺀 글자
        return re.sub(r"\(.*\)$", "", re.sub(r"\s", "", t))
    stats = []
    for p in range(1, n + 1):
        ls = [d for d in lines_of(p) if not d["is_page_number"]]
        texts = [d["text"].strip() for d in ls]
        stats.append({"page": p, "n_lines": len(ls), "toc_lines": sum(bool(leader.search(t)) for t in texts),
                      "heading_start": any(FIRST_HEADING.match(t) or bare(t) in unnumbered
                                           for t in texts if not leader.search(t))})
    toc = {s["page"] for s in stats if s["toc_lines"] >= 3}
    if toc:  # 첫 목차 쪽부터 본문
        first = min(toc)
    else:
        first = next((s["page"] for s in stats if s["page"] > 1 and s["heading_start"]), None)
    zones = []
    for s in stats:
        p = s["page"]
        name = "목차·간지" if p in toc else "앞단" if (p == 1 or (first and p < first)) else "본문"
        s["candidate"] = name
        if zones and zones[-1][2] == name:
            zones[-1][1] = p
        else:
            zones.append([p, p, name, name not in EXCLUDED])
    return zones, stats


def main() -> int:
    setup("auto_zones")
    d = doc()
    if d.get("zones_status") != "provisional":
        out("skip", reason="zones_not_provisional", status=d.get("zones_status") or "checked")
        return 0
    n = int(d["pages"])
    kind = profile().get("auto_zones", "generic")
    if kind == "report":
        zones, stats = report_zones(n)
        return finish(n, zones, stats, kind)
    from tools.zones import candidate, page_stats

    generic = kind != "insurance"
    stats, carry = [], "앞단"
    for p in range(1, n + 1):
        s = page_stats(p)
        # 제목 폰트 편·관·조 줄이 있는 쪽은 글자가 적어도 간지가 아니다 (짧은 특약의 첫 쪽: 제목 띠 + 조 몇 개)
        has_titles = s["pyeon_title"] or s["gwan_title"] or s["art_n_title"] or s["art_nm_title"]
        s_rule = {**s, "band_font_lines": 0, "big_lines": 0} if has_titles else s
        cand, rule = candidate(s_rule, carry, any(x["candidate"] == "특약" for x in stats),
                               any(x["candidate"] == "장해분류표" for x in stats))
        s.update(candidate=cand, rule=rule)
        stats.append(s)
        if rule not in ("빈쪽", "글자적음+큰제목"):  # 간지 한 장은 뒤 쪽으로 잇지 않는다
            carry = cand
    zones = []
    for s in stats:
        name = "본문" if generic and s["candidate"] not in EXCLUDED else s["candidate"]
        if zones and zones[-1][2] == name:
            zones[-1][1] = s["page"]
        else:
            zones.append([s["page"], s["page"], name, name not in EXCLUDED])
    return finish(n, zones, stats, kind)


def finish(n: int, zones: list[list], stats: list[dict], kind: str) -> int:
    fallback = not any(z[3] for z in zones)
    if fallback:
        zones = [[1, n, "본문", True]]
    with open(result_path(RESULTS / "parsing" / "auto_zones.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(stats[0].keys()))
        w.writeheader()
        w.writerows(stats)
    set_zones(DOCS_DIR / f"{doc_id()}.yaml", zones, "auto")
    for a, b, z, inc in zones:
        out("zone", pages=f"{a}-{b}", zone=Trusted(z), included=inc)
    if fallback:
        out("warn", reason="no_included_pages_detected_all_pages_included")
    out("done", mode=kind, zones=len(zones),
        included_pages=sum(b - a + 1 for a, b, _, inc in zones if inc), pages=n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
