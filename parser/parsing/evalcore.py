"""공용: secure의 쪽별 덤프 읽기 (줄·글자·영역·그리기 객체), 1주차 표 파서 입력 재구성, 상자 계산.

좌표는 모두 pt, top-down [x0, top, x1, bottom]. 원문은 다루기만 하고 출력하지 않는다 (출력은 safeio로).
"""

import json
from functools import lru_cache

from config import P
from safeio import SECURE

LINES_DIR = SECURE / "lines"
CHAR_TOL = P("geometry.char_center_tol_pt")  # 글자 중심이 영역 안인지 볼 때 허용 오차 (pt)


@lru_cache(maxsize=None)
def pages_meta() -> dict[int, dict]:
    return {int(k): v for k, v in json.loads((LINES_DIR / "pages.json").read_text(encoding="utf-8")).items()}


@lru_cache(maxsize=96)
def page_dump(page: int) -> dict:
    """pdf_lines.py가 쓴 쪽별 파일 (meta, lines, chars, regions, dropped). 최근 쪽만 메모리에 둔다."""
    p = LINES_DIR / "by_page" / f"p{page:03d}.json"
    if not p.exists():
        return {"meta": {}, "lines": [], "chars": [], "regions": [], "dropped": []}
    return json.loads(p.read_text(encoding="utf-8"))


class PageObjects:
    """쪽별 파일에 저장한 그리기 객체 (pdf_lines.page_objects_dump). pdfplumber Page처럼 rects·lines·curves를 dict 목록으로 준다."""

    def __init__(self, d: dict):
        self.rects, self.lines, self.curves = d["rects"], d["lines"], d["curves"]

    def flush_cache(self) -> None:
        pass


def page_objects(page: int) -> PageObjects:
    return PageObjects(page_dump(page)["objects"])


def page_geometry(page: int):
    """1week-rag PageGeometry를 저장한 선분·글자로 다시 만든다 (PDF를 다시 읽지 않음)."""
    from pdf_lines import WEEK1  # noqa: F401  (1주차 표 파서 복사본 vendor/ 경로를 sys.path에 넣는다)
    from policy_rag.ingest.extract import Char, PageGeometry, Segment

    d = page_dump(page)
    obj = d["objects"]
    chars = [Char(text=c["text"], x0=r[0], x1=r[1], top=r[2], bottom=r[3], fontname=c["font"], size=r[4])
             for c, r in zip(d["chars"], obj["chars_raw"])]
    return PageGeometry(page=page, width=d["meta"]["width"], height=d["meta"]["height"],
                        segments=[Segment(o, pos, s, e) for o, pos, s, e in obj["segments"]], chars=chars,
                        obj_counts=obj.get("obj_counts", {}), image_bboxes=d["meta"]["image_bboxes"])


def lines_of(page: int) -> list[dict]:
    return page_dump(page)["lines"]


def chars_of(page: int, with_space: bool = False) -> list[dict]:
    """공백 아닌 글자만 (with_space면 공백 글자도)."""
    return [c for c in page_dump(page)["chars"] if with_space or c["text"].strip()]


def regions_of(page: int) -> list[dict]:
    return page_dump(page)["regions"]


def area(b) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def inter(a, b) -> float:
    return max(min(a[2], b[2]) - max(a[0], b[0]), 0.0) * max(min(a[3], b[3]) - max(a[1], b[1]), 0.0)


def inside(box, outer, tol: float) -> bool:
    return (box[0] >= outer[0] - tol and box[1] >= outer[1] - tol
            and box[2] <= outer[2] + tol and box[3] <= outer[3] + tol)


def center_in(c: dict, b, tol: float = CHAR_TOL) -> bool:
    cx, cy = (c["x0"] + c["x1"]) / 2, (c["top"] + c["bottom"]) / 2
    return b[0] - tol <= cx <= b[2] + tol and b[1] - tol <= cy <= b[3] + tol

