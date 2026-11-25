"""영역 판정 확인용 출력: 표 모양 리포트 (results/parsing/tables_classify.md), 와이어프레임 (review/wireframe/).

tables_classify.py가 --review (safeio.review_mode())일 때 부른다. 원문이 든 파일은 secure/review/에만 쓴다."""

from collections import Counter

from evalcore import lines_of, page_geometry, page_objects, pages_meta
from pdf_lines import md_table
from safeio import RESULTS, result_path, review_wireframe_path, review_write
from samples import FINAL_ZONES, RANDOM15, SAMPLE45
from tables_classify import TITLE_BAND_FONTS


SHAPES = ("a", "b", "c", "d")


SHAPE_NAME = {"a": "격자 다 있음", "b": "머리 행 선·열 구분선만", "c": "선 거의 없음", "d": "라벨 열 + 내용 열"}


def write_report(tables: list[dict], skipped: Counter) -> None:
    tt = [t for t in tables if t["decided"] == "table"]
    zones = []
    for a, b, z, inc in FINAL_ZONES:
        if inc and z not in zones:
            zones.append(z)
    parts = ["# 표 영역 확정과 모양 분류 (2차 2단계 2-1, 포함 693쪽, 집계만)", "",
             "정의는 `parsing/tables_classify.py` 머리말. 글자가 있는 영역만 센다.", "",
             "## 영역 종류 결정", "",
             md_table(["결정", "영역 수"], [
                 [f"제목 띠 ({'·'.join(sorted(TITLE_BAND_FONTS))} 줄 포함)", sum(t["decided"] == "title_band" for t in tables)],
                 ["① 표 검사 통과 → 표", sum(t["step"] == "1" for t in tt)],
                 ["② 박스 라벨 → 박스 (대상 아님)", sum(t["decided"] == "box" for t in tables)],
                 ["  그중 격자 검사 통과 (예전 순서였으면 ① 표)", sum(t["decided"] == "box" and t.get("passed") for t in tables)],
                 ["③ 글자 2행 이상 + 라벨 열 구분 또는 안쪽 세로선 → 표", sum(t["step"] == "3" for t in tt)],
                 ["③ 그 밖 → 본문", sum(t["decided"] == "body" for t in tables)],
                 ["제외 영역 (image·broken·example_box)과 50% 이상 겹쳐 다루지 않음", skipped["excluded_overlap"]],
             ]), "",
             f"- 제목 띠의 원래 종류: {', '.join(f'{k} {v}' for k, v in Counter(t['kind'] for t in tables if t['decided'] == 'title_band').most_common()) or '-'}.", ""]
    parts += ["## 모양별·구역별 표 수", "",
              md_table(["모양", "설명"] + zones + ["합계"],
                       [[s, SHAPE_NAME[s]] + [sum(1 for t in tt if t["shape"] == s and t["zone"] == z) for z in zones]
                        + [sum(1 for t in tt if t["shape"] == s)] for s in SHAPES]
                       + [["합계", ""] + [sum(1 for t in tt if t["zone"] == z) for z in zones] + [len(tt)]]), "",
              "## 모양 × 결정 단계", "",
              md_table(["모양", "①", "③", "머리 행 채움 있음"],
                       [[s] + [sum(1 for t in tt if t["shape"] == s and t["step"] == st) for st in ("1", "3")]
                        + [sum(1 for t in tt if t["shape"] == s and t["header_fill"])] for s in SHAPES]), "",
              "## 샘플별", "",
              md_table(["샘플", "표"] + list(SHAPES),
                       [[name, sum(1 for t in tt if f(t["page"]))] + [sum(1 for t in tt if f(t["page"]) and t["shape"] == s) for s in SHAPES]
                        for name, f in (("sample45", lambda p: p in SAMPLE45), ("random15", lambda p: p in RANDOM15),
                                        ("그 밖", lambda p: p not in SAMPLE45 and p not in RANDOM15))]), ""]
    path = result_path(RESULTS / "parsing" / "tables_classify.md")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def pick_examples(tables: list[dict]) -> list[dict]:
    """모양마다 3개 (샘플 45쪽 먼저, 무작위 15쪽 제외), 제목 띠 2개."""
    s45, r15 = set(SAMPLE45), set(RANDOM15)
    picked = []
    for key in list(SHAPES) + ["title_band"]:
        pool = [t for t in tables if ((t["decided"] == "table" and t.get("shape") == key) if key != "title_band"
                                      else t["decided"] == "title_band") and t["page"] not in r15]
        pool.sort(key=lambda t: (t["page"] not in s45, t["page"]))
        seen_pages = set()
        for t in pool:
            if t["page"] in seen_pages:
                continue
            seen_pages.add(t["page"])
            picked.append({**t, "_key": key})
            if len(seen_pages) >= (2 if key == "title_band" else 3):
                break
    return picked


def write_wireframes(examples: list[dict], list_name: str, question: str) -> None:
    """쪽 전체 와이어프레임: 줄 상자 (회색 채움), 영역 bbox (색 = 모양 또는 바뀐 결정), 선분 (검정), 채움 사각형 (연파랑),
    라벨 열 구분 (빨강). 글자는 그리지 않는다."""
    from contextlib import nullcontext

    from PIL import Image, ImageDraw

    from draw import draw_label, label_font

    colors = {"a": (0, 150, 0), "b": (0, 90, 255), "c": (230, 120, 0), "d": (200, 0, 200), "title_band": (120, 120, 120)}
    rows = ["# 표 모양 예시 (구조 수치만, 글자 없음)", "",
            "와이어프레임: `review/wireframe/<table_id>_<모양>.png` (회색 = 글자 줄 상자, 검정 = 선분, 연파랑 = 채움 사각형, "
            "빨강 세로선 = 라벨 열 구분, 테두리 색 = 모양).", "",
            "| table_id | page | zone | 모양 | 결정 단계 | 출처 | pdfplumber 격자 | 가로선 | 안쪽 세로선 | 글자 행 | 구분된 행 사이 | 머리 행 채움 | 글자 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    with nullcontext():
        for t in examples:
            p = t["page"]
            meta = pages_meta()[p]
            s = 2.0
            img = Image.new("RGB", (int(meta["width"] * s), int(meta["height"] * s)), (255, 255, 255))
            d = ImageDraw.Draw(img)
            page = page_objects(p)
            for o in page.rects:
                if o.get("fill") and float(o["x1"]) - float(o["x0"]) > 2.5 and float(o["bottom"]) - float(o["top"]) > 2.5:
                    d.rectangle([float(o["x0"]) * s, float(o["top"]) * s, float(o["x1"]) * s, float(o["bottom"]) * s], fill=(215, 232, 250))
            for ln in lines_of(p):
                d.rectangle([ln["x0"] * s, ln["top"] * s, ln["x1"] * s, ln["bottom"] * s], fill=(200, 200, 200))
            geom = page_geometry(p)
            for sg in geom.segments:
                pts = [(sg.start * s, sg.pos * s), (sg.end * s, sg.pos * s)] if sg.orient == "h" else \
                    [(sg.pos * s, sg.start * s), (sg.pos * s, sg.end * s)]
                d.line(pts, fill=(0, 0, 0), width=1)
            key = t["_key"]
            color = colors.get(key, colors.get(t.get("shape") if t["decided"] == "table" else t["decided"], (230, 0, 0)))
            b = t["bbox"]
            d.rectangle([b[0] * s, b[1] * s, b[2] * s, b[3] * s], outline=color, width=4)
            if t.get("sep_x"):
                d.line([(t["sep_x"] * s, b[1] * s), (t["sep_x"] * s, b[3] * s)], fill=(230, 0, 0), width=3)
            tid = t.get("table_id") or f"p{p:03d}_{t['source'].split('#')[-1].replace(':', '_')}"
            draw_label(d, label_font(), b[1] * s, f"{tid} {key}", color)
            page.flush_cache()
            img.save(review_wireframe_path(f"wireframe/{tid}_{key}.png", p, f"wireframe/ ({list_name})", question))
            rows.append(f"| {tid} | {p} | {t['zone']} | {key} | {t['step']} | {t['source']} | {t['grid']} | {t.get('n_h', '-')} | "
                        f"{t.get('n_v_inner', '-')} | {t.get('rows_text', '-')} | {t.get('ruled_gaps', '-')} | "
                        f"{t.get('header_fill', '-')} | {t.get('n_chars', '-')} |")
    review_write(list_name, rows, question, {t["page"] for t in examples})
