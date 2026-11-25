"""표 추출 확인용 출력: 리포트 (results/parsing/tables_report.md), 와이어프레임, 사람 확인용 표·그림 (secure/review/).

tables_extract.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter
from pathlib import Path

from config import P
from evalcore import lines_of
from pdf_lines import md_table
from safeio import RESULTS, SECURE, out, result_path, review_wireframe_path, review_write, secure_path, secure_review_write
from samples import RANDOM15, SAMPLE45


def _pct(a, b) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def write_report(recs: list[dict], n_merge: int) -> None:
    def stats(sel):
        return [len(sel), sum(len(r["rows"]) for r in sel), sum(1 for r in sel if r["header"]),
                sum(1 for r in sel if r["notes"]), sum(1 for r in sel if r["title"]), sum(1 for r in sel if r["intro"]),
                sum(1 for r in sel if r["prev_numbered"]), sum(1 for r in sel if len(r["pages"]) > 1),
                sum(1 for r in sel if r["confidence"] == "low")]

    hdr = ["표", "행", "머리 행 있음", "아래 주석 붙음", "표 제목", "도입 줄", "앞 번호 줄", "쪽 넘김 합침", "확신 낮음"]
    parts = ["# 표 추출 (2차 2단계 2-2~2-5, 집계만)", "",
             "정의는 `parsing/tables_extract.py` 머리말. 표 수는 쪽 넘김으로 이어 붙인 뒤의 수.", "",
             "## 모양별", "", md_table(["모양", "방법"] + hdr,
                                     [[s, Counter(r["method"] for r in recs if r["shape"] == s).most_common(1)[0][0]]
                                      + stats([r for r in recs if r["shape"] == s]) for s in ("a", "b", "c", "d")
                                      if any(r["shape"] == s for r in recs)]), "",
             "## 구역별", "", md_table(["구역"] + hdr, [[z] + stats([r for r in recs if r["zone"] == z])
                                                   for z in dict.fromkeys(r["zone"] for r in recs)]), "",
             "## 샘플별 (무작위 15쪽은 검증용, 지표만)", "",
             md_table(["샘플"] + hdr, [[n] + stats([r for r in recs if f(r["page"])]) for n, f in
                                     (("sample45", lambda p: p in SAMPLE45), ("random15", lambda p: p in RANDOM15),
                                      ("그 밖", lambda p: p not in SAMPLE45 and p not in RANDOM15))]), "",
             "## 자동 검증", ""]
    cells = [c for r in recs for row in r["rows"] for c in row]
    flags = Counter(f for r in recs for f in r["flags"])
    parts += [md_table(["항목", "값"], [
        ["행마다 열 수가 다른 표", flags["col_mismatch"]],
        ["숫자 열에 숫자 아닌 칸이 있는 표", flags["numeric_col_nonnumeric"]],
        ["빈 칸 비율 (전체 본문 칸)", _pct(sum(1 for c in cells if not c), len(cells))],
        [f"빈 칸 비율 > {P('table_extract.empty_ratio_low')}인 표", flags["many_empty"]],
        ["격자 검사 실패 (a, ③에서 표가 된 것)", flags["grid_check_failed"]],
        ["이미지 칸 (c)", flags["image_cells"]],
        ["행이 없는 표", flags["no_rows"]],
        ["쪽 넘김 이어 붙임 횟수", n_merge],
        ["(b)·(c) 중 행 시작 표시 기준으로 묶은 표", sum(1 for r in recs if r.get("marker_mode"))],
    ]), "", "## 확신 낮은 표 (table_id, 이유)", ""]
    low = [r for r in recs if r["confidence"] == "low"]
    parts += [", ".join(f"{r['table_id']} ({'/'.join(r['flags'])})" for r in low) or "-", ""]
    path = result_path(RESULTS / "parsing" / "tables_report.md")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def write_examples(recs: list[dict]) -> None:
    """모양별 예시 2개 (샘플 45쪽 먼저, 무작위 15쪽 제외): 추출한 행·열 경계를 그린 와이어프레임 (글자 없음)."""
    from PIL import Image, ImageDraw

    from draw import draw_label, label_font
    from evalcore import pages_meta

    picked = []
    for s in ("a", "b", "c", "d"):
        pool = sorted([r for r in recs if r["shape"] == s and r["page"] not in RANDOM15],
                      key=lambda r: (r["page"] not in SAMPLE45, len(r["pages"]) == 1, r["page"]))
        picked += pool[:2]
    rows = ["# 표 추출 예시 (구조만)", "", "와이어프레임: 회색 = 글자 줄, 파랑 = 추출한 열 경계, 빨강 = 표 영역, 초록 = 행 경계 (격자)", "",
            "| table_id | 쪽 | 모양 | 방법 | 열 | 머리 행 | 본문 행 | 주석 | 표 제목 | 도입 줄 | 앞 번호 줄 패턴 | 확신 | 이유 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in picked:
        p = r["page"]
        meta = pages_meta()[p]
        sc = 2.0
        img = Image.new("RGB", (int(meta["width"] * sc), int(meta["height"] * sc)), (255, 255, 255))
        d = ImageDraw.Draw(img)
        for ln in lines_of(p):
            d.rectangle([ln["x0"] * sc, ln["top"] * sc, ln["x1"] * sc, ln["bottom"] * sc], fill=(200, 200, 200))
        b = r["bbox"]
        d.rectangle([v * sc for v in b], outline=(230, 0, 0), width=3)
        for x in r["col_x"]:
            d.line([(x * sc, b[1] * sc), (x * sc, b[3] * sc)], fill=(0, 90, 255), width=2)
        for y in r.get("row_y", []):
            d.line([(b[0] * sc, y * sc), (b[2] * sc, y * sc)], fill=(0, 150, 0), width=2)
        draw_label(d, label_font(), b[1] * sc, f"{r['table_id']} {r['shape']}", (230, 0, 0))
        img.save(review_wireframe_path(f"wireframe/extract_{r['table_id']}.png", p, "wireframe/extract_<table_id>.png",
                                       "추출한 열 경계·행 경계가 표 모양과 맞는가"))
        rows.append(f"| {r['table_id']} | {','.join(map(str, r['pages']))} | {r['shape']} | {r['method']} | {r['n_cols']} | "
                    f"{len(r['header'])} | {len(r['rows'])} | {len(r['notes'])} | {'Y' if r['title'] else '-'} | "
                    f"{'Y' if r['intro'] else '-'} | {r['prev_numbered']['pattern'] if r['prev_numbered'] else '-'} | "
                    f"{r['confidence']} | {'/'.join(r['flags']) or '-'} |")
    review_write("tables_extract_examples.md", rows, "표 추출 예시의 구조 수치 (와이어프레임과 함께)", {r["page"] for r in picked})


def write_user_check(recs: list[dict]) -> None:
    """사람 확인용 (원문, secure/review): 장해분류표 (유첨 b) 3개, 지급사유·지급금액 (d) 3개, 격자 (a) 2개."""
    s = [r for r in recs if r["page"] not in RANDOM15]
    pick = ([r for r in s if r["zone"] == "유첨" and r["shape"] == "b"][:3] + [r for r in s if r["shape"] == "d"][:3]
            + [r for r in s if r["shape"] == "a"][:2])
    write_check(pick, "tables_check", "표 추출 확인 (사람 확인용): 숫자가 행과 맞게 붙었는지", {})


def write_flagged_check(recs: list[dict]) -> int:
    """사람 판단용 (원문, secure/review/tables_flagged): 확신 낮은 표 (이미지 칸은 뺌)와
    (a) 중 이중 테두리 틈새를 지운 뒤 머리 행이 없어진 표. 무작위 15쪽은 넣지 않는다 (검증용)."""
    reasons = {}
    for r in recs:
        if r["page"] in RANDOM15:
            continue
        why = [f for f in r["flags"] if f != "image_cells"]
        if r["method"] == "grid" and r.get("header_rows_1week", 0) > 0 and not r["header"]:
            why.append("header_lost_after_sliver")
        if why:
            reasons[r["table_id"]] = why
    pick = [r for r in recs if r["table_id"] in reasons]
    write_check(pick, "tables_flagged", "판단이 필요한 표 (확신 낮음, 머리 행 사라짐)", reasons)
    return len(pick)


def _save_retry(img, path: Path, tries: int = 10) -> None:
    """편집기 미리보기가 그림을 다시 읽는 동안 Windows가 파일을 잠깐 잠그면 저장이 실패한다. 잠시 기다렸다 다시 쓴다."""
    import time

    for k in range(tries):
        try:
            img.save(path)
            return
        except OSError as e:
            if k == tries - 1:
                out("save_failed", file=path.stem, errno=e.errno, winerror=getattr(e, "winerror", None))
                raise
            time.sleep(0.3)


def write_check(pick: list[dict], name: str, title: str, reasons: dict[str, list[str]]) -> None:
    from PIL import Image, ImageDraw

    from evalcore import pages_meta

    reason_text = {"grid_check_failed": "격자 검사 실패한 영역을 격자로 추출함", "numeric_col_nonnumeric": "숫자 열에 숫자 아닌 칸",
                   "many_empty": "빈 칸 비율 높음", "col_mismatch": "행마다 열 수 다름", "no_rows": "행 없음",
                   "header_lost_after_sliver": "틈새 행을 지운 뒤 머리 행이 없어짐 (1주차는 머리 행으로 봄)"}
    rows = [f"# {title}", "",
            f"쪽 그림: `secure/review/{name}/<table_id>.png`. 빨강 = 표 영역. (a) 격자: 초록 상자 = 추출한 칸 하나 "
            "(병합 칸은 큰 상자 하나). (d) 라벨+내용: 보라 상자 = 라벨 하나, 초록 선 = 내용 행 경계, 파랑 = 라벨/내용 경계. "
            "(b)·(c): 파랑 = 열 경계, 초록 = 본문 행 시작, 주황 = 머리 행 경계.", ""]
    if reasons:
        rows += ["| table_id | 쪽 | 모양 | 이유 |", "|---|---|---|---|"]
        rows += [f"| {r['table_id']} | {','.join(map(str, r['pages']))} | {r['shape']} | "
                 f"{'; '.join(reason_text.get(w, w) for w in reasons[r['table_id']])} |" for r in pick]
        rows.append("")
    for r in pick:
        for k, (p, b) in enumerate(zip(r["pages"], r["bboxes"])):
            render = SECURE / "renders" / f"p{p:03d}.png"
            if not render.exists():
                continue
            img = Image.open(render).convert("RGB")
            sc = img.width / pages_meta()[p]["width"]
            d = ImageDraw.Draw(img)
            d.rectangle([v * sc for v in b], outline=(230, 0, 0), width=3)
            g = r["page_draw"][k] if "page_draw" in r else r  # 이 쪽의 칸 좌표
            if r["method"] == "grid":  # 실제 칸 (병합 반영)을 그린다
                xs, ys = g["grid_xs"], g["grid_ys"]
                for c in g["cells"]:
                    cx0, cy0 = xs[c["c"]] * sc, ys[c["r"]] * sc
                    cx1, cy1 = xs[min(c["c"] + c["cs"], len(xs) - 1)] * sc, ys[min(c["r"] + c["rs"], len(ys) - 1)] * sc
                    inset = 2 if cx1 - cx0 > 6 and cy1 - cy0 > 6 else 0  # 좁은 칸은 들이지 않는다
                    if cx1 > cx0 and cy1 > cy0:
                        d.rectangle([cx0 + inset, cy0 + inset, cx1 - inset, cy1 - inset], outline=(0, 160, 0), width=2)
            elif r["method"] == "label_content":  # 행 선은 내용 열에만, 라벨 칸은 상자로
                sep = g["col_x"][1]
                for y in g.get("row_y", []):
                    d.line([(sep * sc, y * sc), (b[2] * sc, y * sc)], fill=(0, 160, 0), width=2)
                for top, bot in g.get("label_spans", []):
                    d.rectangle([b[0] * sc + 3, (top - 1) * sc, sep * sc - 3, (bot + 1) * sc], outline=(200, 0, 200), width=2)
                d.line([(sep * sc, b[1] * sc), (sep * sc, b[3] * sc)], fill=(0, 90, 255), width=2)
            else:
                for x in g["col_x"]:
                    d.line([(x * sc, b[1] * sc), (x * sc, b[3] * sc)], fill=(0, 90, 255), width=2)
                for y in g.get("row_y", []):
                    if b[1] - 2 <= y <= b[3] + 2:
                        d.line([(b[0] * sc, y * sc), (b[2] * sc, y * sc)], fill=(0, 160, 0), width=2)
            hy = g.get("header_y")
            if hy is not None and b[1] - 2 <= hy <= b[3] + 2:
                d.line([(b[0] * sc, hy * sc), (b[2] * sc, hy * sc)], fill=(255, 140, 0), width=3)
            suffix = f"_{k + 1}" if len(r["pages"]) > 1 else ""
            _save_retry(img, secure_path(SECURE / "review" / name / f"{r['table_id']}{suffix}.png"))
        rows += [f"## {r['table_id']} (쪽 {', '.join(map(str, r['pages']))}, 모양 {r['shape']}, {r['method']}, 확신 {r['confidence']})", ""]
        if r["title"]:
            rows.append(f"- 표 제목: {r['title']['text']}")
        if r["intro"]:
            rows.append(f"- 도입 줄: {r['intro']['text']}")
        if r["prev_numbered"]:
            rows.append(f"- 앞 번호 줄 (쪽 {r['prev_numbered']['page']}): {r['prev_numbered']['text']}")
        rows.append("")
        width = r["n_cols"]
        head = r["header"][0] if r["header"] else [f"열{k + 1}" for k in range(width)]
        rows.append("| " + " | ".join(h.replace("|", "/") for h in head) + " |")
        rows.append("|" + "---|" * len(head))
        for row in r["rows"]:
            rows.append("| " + " | ".join(c.replace("|", "/") for c in row) + " |")
        if r["notes"]:
            rows += ["", "주석: " + " / ".join(r["notes"])]
        rows.append("")
    secure_review_write(f"{name}.md", rows)
