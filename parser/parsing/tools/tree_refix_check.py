"""사람 확인용: 지정한 쪽의 트리 항목을 쪽 그림 위에 단계별 색 상자로 그린다 (secure/review/tree_refix/).

상자 옆 글자 = "L<조 아래 단계> <읽은 번호>" (글머리표는 *). 색: L1 빨강, L2 파랑, L3 초록, L4 보라, 주석 주황.
목록이 맞게 나뉘었는지 PDF 쪽과 비교하는 용도. md에는 해당 조의 트리 (원문)를 단계별로 적는다.
실행 (requirements.txt 환경): python parsing/tools/tree_refix_check.py <쪽> [<쪽> ...]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # parsing/ (공용 모듈)
from evalcore import lines_of, pages_meta  # noqa: E402
from safeio import SECURE, out, secure_path, secure_review_write, setup  # noqa: E402
from samples import RANDOM15  # noqa: E402

COLORS = {1: (220, 0, 0), 2: (0, 90, 255), 3: (0, 160, 0), 4: (160, 0, 200)}


def main() -> int:
    setup("tree_refix_check")
    from PIL import Image, ImageDraw, ImageFont

    pages = [int(a) for a in sys.argv[1:] if int(a) not in RANDOM15]
    nodes = [json.loads(s) for s in (SECURE / "tree" / "nodes.jsonl").read_text(encoding="utf-8").splitlines()]
    by = {n["id"]: n for n in nodes}
    try:
        fnt = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        fnt = ImageFont.load_default()
    arts = []
    for pg in pages:
        line_at = {d["line_id"]: d for d in lines_of(pg)}
        img = Image.open(SECURE / "renders" / f"p{pg:03d}.png").convert("RGB")
        sc = img.width / pages_meta()[pg]["width"]
        dr = ImageDraw.Draw(img)
        for n in nodes:
            if n["type"] not in ("item", "note") or not n["lines"] or n["lines"][0]["page"] != pg:
                continue
            a = by.get(n["article_id"]) if n["article_id"] else None
            lvl = n["depth"] - (a["depth"] if a else min(m["depth"] for m in nodes if m["type"] == "item"))
            if a and a["id"] not in arts:
                arts.append(a["id"])
            ln = line_at[n["lines"][0]["line_id"]]
            col = (255, 140, 0) if n["type"] == "note" else COLORS.get(lvl, (90, 90, 90))
            box = [ln["x0"] * sc - 3, ln["top"] * sc - 2, ln["x1"] * sc + 3, ln["bottom"] * sc + 2]
            dr.rectangle(box, outline=col, width=3)
            tag = "note" if n["type"] == "note" else f"L{lvl} {n['number'] if n['number'] is not None else '*'}"
            dr.rectangle([4, box[1], 70, box[1] + 18], fill=(255, 255, 255))
            dr.text((6, box[1]), tag, fill=col, font=fnt)
        img.save(secure_path(SECURE / "review" / "tree_refix" / f"p{pg:03d}.png"))

    def render(n, ind=0):
        lab = {"note": "[주석] "}.get(n["type"], "")
        rows = [f"{'  ' * ind}- {lab}{(n['title'] or '') + ' ' if n['title'] else ''}{n['text'][:90]}"]
        for k in n["children"]:
            rows += render(by[k], ind + 1)
        return rows

    rows = ["# 번호 목록 다시 확인 (사람 확인용)", "",
            "그림: `secure/review/tree_refix/p<쪽>.png`. 상자 왼쪽 여백 글자 = L<조 아래 단계> <번호> (글머리표 *). "
            "색: L1 빨강, L2 파랑, L3 초록, L4 보라, 주석 주황.", ""]
    for aid in arts:
        a = by[aid]
        rows += [f"## {a['title']} (쪽 {a['page_start']}-{a['page_end']})", ""] + render(a) + [""]
    secure_review_write("tree_refix.md", rows)
    out("done", pages=len(pages), articles=len(arts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
