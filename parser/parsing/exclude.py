"""1단계 제외: 포함 쪽 안 제외 영역 표시 (지우지 않고 이유만 붙인다).

제외 이유 (글자 하나에 여러 이유가 겹치면 이 순서로 하나만 센다):
  page_number: 쪽번호 줄 (pdf_lines 규칙)
  header: 쪽 위 exclude.header_top_ratio 안의 양식 코드 줄 (프로필 fonts.form_code 폰트 + form_code_regex 모양).
          같은 줄의 여러 쪽 반복은 쓰지 않는다 (이 문서에서는 특약끼리 같은 조항·별표 제목이 되풀이될 뿐 머리말이 아님).
          프로필 running_header: true면 쪽 위 머리글도 header: 쪽 위 exclude.header_top_ratio 안에서 본문보다 작은 글씨이고
          본문 크기 줄보다 위에 있는 줄 (보고서의 "사실정보 한국철도공사 …" 같은 장 이름 + 문서 제목 줄).
  image: pdfplumber 래스터 이미지 (두 변 ≥ exclude.raster_min_side_pt). exclude.image_max_page_ratio가 있으면 쪽 넓이의
         그 비율보다 큰 이미지는 쓰지 않고, exclude.image_keep_body_text면 이미지 안이라도 본문 크기 글자 (본문 크기 - 0.5pt
         이상)는 남긴다 (보고서: 그림과 겹친 본문 문장은 살리고 그림 안 작은 이름표만 뺀다)
  broken (잠정): 글자 배정 검사 실패 영역 중 화살표 문자 (exclude.arrow_codepoints)가 있고 박스 라벨
          (프로필 box_kinds_not_table)이 아닌 것
  example_box: 박스 안 굵은 꺾쇠 줄 (< >로 시작·끝, "예시" 포함)부터 같은 박스 끝까지 (boxes.py).
               단 설명 박스 (프로필 example.keep_in_box_kinds) 안 예시는 주요 계산식이라 제외하지 않는다
줄 표시: 줄 글자의 exclude.line_excluded_ratio 이상이 제외면 excluded=True, reason = 가장 많은 이유.
설정: config/profiles/<프로필>.yaml (양식 코드 폰트·정규식, 박스 라벨), config/params.yaml (exclude 임계값).

출력: secure/lines/lines_marked.jsonl, results/parsing/excluded_regions.csv
확인용 출력 (--review, parsing/review/exclude.py): results/parsing/exclusion_full_report.md, secure/review/broken_full.md
실행 (requirements.txt 환경): python parsing/exclude.py
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evalcore import LINES_DIR, center_in, chars_of, lines_of, pages_meta, regions_of  # noqa: E402
from config import P, box_kinds_not_table, caption_kind, font, form_code_re, profile  # noqa: E402
from safeio import RESULTS, ROOT, Trusted, rel, out, result_path, review_mode, secure_path, setup  # noqa: E402
from samples import INCLUDED_PAGES, RANDOM15, SAMPLE45, zone_of  # noqa: E402

REASONS = ("page_number", "header", "image", "broken", "example_box")
BOX_LABEL_KINDS = box_kinds_not_table()
ARROWS = range(P("exclude.arrow_codepoints")[0], P("exclude.arrow_codepoints")[1] + 1)
HEADER_TOP = P("exclude.header_top_ratio")
RASTER_MIN = P("exclude.raster_min_side_pt")
CODE_LINE = form_code_re()  # 양식 코드 줄 (header로 제외), 회사 스타일 프로필 form_code_regex


def body_size(pages) -> float:
    """본문 글자 크기: 프로필 body 폰트 키의 크기, 없으면 (UNSET) 포함 쪽 줄 크기의 최빈값."""
    s = float(font("body").rsplit("/", 1)[1])
    if s > 0:
        return s
    c = Counter(round(d["size"]) for p in pages for d in lines_of(p) if not d["is_page_number"])
    return float(c.most_common(1)[0][0]) if c else 0.0


def code_lines(pages) -> tuple[dict[tuple[int, int], str], int]:
    """쪽 위 HEADER_TOP 안의 양식 코드 폰트 (프로필 fonts.form_code) 줄 중 코드 모양인 것, 그리고 (프로필 running_header)
    쪽 위 머리글 줄. 반환: ({(page, line_id): form_code|running_header}, 양식 코드 폰트인데 코드 모양이 아닌 쪽 위 줄 수)."""
    hits, other = {}, 0
    code_font = font("form_code")
    running = bool(profile().get("running_header"))
    bs = body_size(pages) if running else 0.0
    for p in pages:
        h = pages_meta()[p]["height"]
        top_lines = [d for d in lines_of(p) if d["top"] <= HEADER_TOP * h and not d["is_page_number"]]
        for d in top_lines:
            if not d["font_key"].startswith(code_font):
                continue
            if CODE_LINE.fullmatch(d["text"].strip()):
                hits[(p, d["line_id"])] = "form_code"
            else:
                other += 1
        if running and bs:
            limit = min((d["top"] for d in top_lines if d["size"] >= bs - 0.5), default=HEADER_TOP * h)
            for d in top_lines:
                if d["top"] < limit and d["size"] < bs - 0.5:
                    hits.setdefault((p, d["line_id"]), "running_header")
    return hits, other


def load_boxes() -> dict[str, dict]:
    path = LINES_DIR / "boxes.json"
    return {b["region_id"]: b for b in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}


def page_exclusions(p: int, boxes: dict, codes: set) -> list[dict]:
    """쪽의 제외 영역 목록: {reason, bbox, source, extra}."""
    ex = []
    for d in lines_of(p):
        bb = [d["x0"], d["top"], d["x1"], d["bottom"]]
        if d["is_page_number"]:
            ex.append({"reason": "page_number", "bbox": bb, "source": f"line{d['line_id']}", "lines": {d["line_id"]}})
        elif (p, d["line_id"]) in codes:
            ex.append({"reason": "header", "bbox": bb, "source": f"line{d['line_id']}:{codes[(p, d['line_id'])]}",
                       "lines": {d["line_id"]}})
    meta = pages_meta()[p]
    page_area = meta["width"] * meta["height"]
    for i, bb in enumerate(meta["image_bboxes"]):
        # 쪽 넓이의 exclude.image_max_page_ratio보다 큰 이미지 (잘라서 일부만 보이는 배경·그림)는 bbox가 본문을 덮어
        # 글자를 잘못 지우므로 제외 영역으로 쓰지 않는다 (설정이 없으면 모든 이미지를 쓴다)
        ratio = P("exclude").get("image_max_page_ratio")
        if ratio and (bb[2] - bb[0]) * (bb[3] - bb[1]) > ratio * page_area:
            continue
        if min(bb[2] - bb[0], bb[3] - bb[1]) >= RASTER_MIN:
            ex.append({"reason": "image", "bbox": bb, "source": f"raster{i}"})
    chars = chars_of(p)
    for r in regions_of(p):
        if r["kind"] != "table" or r["char_ok"] or boxes.get(r["region_id"], {}).get("label_kind") in BOX_LABEL_KINDS:
            continue
        arrows = sum(1 for c in chars if c["region_id"] == r["region_id"] and ord(c["text"][0]) in ARROWS)
        if arrows:
            ex.append({"reason": "broken", "bbox": r["bbox"], "source": f"{r['region_id']}:{r['shape']}:arrows{arrows}"})
    keep = set(profile()["example"].get("keep_in_box_kinds", []))
    for b in boxes.values():
        # 설명 박스 안 예시는 주요 계산식이라 남긴다 (프로필 example.keep_in_box_kinds). 그 밖 상자의 예시만 제외
        if b["page"] == p and b.get("example_range") and b.get("label_kind") not in keep:
            ex.append({"reason": "example_box", "bbox": b["example_range"], "source": b["region_id"]})
    return ex


def char_reasons(p: int, ex: list[dict], keep_size: float = 0.0) -> list[str | None]:
    """글자마다 제외 이유. keep_size > 0이면 그 크기 이상 글자는 image 이유로 빼지 않는다.
    그림·표 설명 줄 (프로필 caption_patterns, "[그림2] 사고 개요")은 그림 안에 있어도 image로 빼지 않는다."""
    res = []
    captions = {d["line_id"] for d in lines_of(p) if caption_kind(d["text"])}
    for c in chars_of(p):
        hit = {e["reason"] for e in ex if ("lines" in e and c["line_id"] in e["lines"])
               or ("lines" not in e and center_in(c, e["bbox"]))}
        if (keep_size and c["size"] >= keep_size) or c["line_id"] in captions:
            hit.discard("image")
        res.append(next((r for r in REASONS if r in hit), None))
    return res


def main() -> int:
    """포함 쪽 전체에 제외 규칙을 적용한다. --full 인자는 예전 호환용 (넣어도 같음)."""
    setup("exclude_full")
    boxes = load_boxes()
    pages = INCLUDED_PAGES
    s45, r15 = set(SAMPLE45), set(RANDOM15)
    codes, code_other = code_lines(pages)
    keep_size = body_size(pages) - 0.5 if P("exclude").get("image_keep_body_text") else 0.0
    all_ex, page_rows = [], []
    reg_n, chr_n = Counter(), Counter()
    zone_tot, zone_exc, zone_ex_regions = Counter(), defaultdict(Counter), defaultdict(Counter)
    total = 0
    with open(secure_path(LINES_DIR / "lines_marked.jsonl"), "w", encoding="utf-8") as mf:
        for p in pages:
            zone, _ = zone_of(p)
            ex = page_exclusions(p, boxes, codes)
            reasons = char_reasons(p, ex, keep_size)
            chars = chars_of(p)
            total += len(chars)
            rc = Counter(r for r in reasons if r)
            chr_n.update(rc)
            zone_tot[zone] += len(chars)
            zone_exc[zone].update(rc)
            for e in ex:
                reg_n[e["reason"]] += 1
                zone_ex_regions[zone][e["reason"]] += 1
                all_ex.append({**e, "page": p, "zone": zone})
            page_rows.append((p, len(chars), sum(rc.values()), rc, zone))
            by_line: dict = defaultdict(list)
            for c, r in zip(chars, reasons):
                by_line[c["line_id"]].append(r)
            for d in lines_of(p):
                rs = by_line.get(d["line_id"], [])
                exc = [r for r in rs if r]
                flag = bool(rs) and len(exc) >= P("exclude.line_excluded_ratio") * len(rs)
                mf.write(json.dumps({**d, "zone_page": zone, "excluded": flag,
                                     "excluded_reason": Counter(exc).most_common(1)[0][0] if flag else None},
                                    ensure_ascii=False) + "\n")

    # 샘플과 비교해 처음 보는 유형 (화면 수치, 확인 리포트)
    sample_max = max((r[2] / r[1] for r in page_rows if r[0] in s45 and r[1]), default=0)
    high = sorted([r for r in page_rows if r[1] and r[2] / r[1] > sample_max], key=lambda r: -r[2] / r[1])
    broken_pages = Counter(e["page"] for e in all_ex if e["reason"] == "broken")

    with open(result_path(RESULTS / "parsing" / "excluded_regions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["page", "zone", "x0", "top", "x1", "bottom", "reason", "source", "set"])
        for e in sorted(all_ex, key=lambda e: (e["page"], e["bbox"][1])):
            w.writerow([e["page"], e["zone"]] + [round(v, 1) for v in e["bbox"]] + [e["reason"], e["source"],
                       "sample45" if e["page"] in s45 else ("random15" if e["page"] in r15 else "full")])

    extra = {}
    if review_mode():  # 기본: 뒤 단계가 읽는 줄 표시·제외 영역만 (리포트·발췌는 확인 모드에서)
        from review.exclude import write_review
        path = write_review(pages, reg_n, chr_n, total, page_rows, zone_tot, zone_exc, codes, code_other,
                            sample_max, high, broken_pages, all_ex)
        extra["report"] = Trusted(rel(path))
    out("done", pages=len(pages), excluded_regions=len(all_ex), reasons=dict(reg_n), chars=dict(chr_n), total_chars=total,
        form_code=len(codes), broken_pages=len(broken_pages), high_pages=len(high), **extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
