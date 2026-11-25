"""PDF에서 선분과 글자 좌표를 추출한다. pdfplumber를 import하는 유일한 모듈.

좌표는 pdfplumber와 같은 top-down(왼쪽 위가 원점), 페이지 번호는 1-based.
예외 메시지에는 문서 내용을 넣지 않는다.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from policy_rag.config import TableConfig


@dataclass
class Char:
    """글자 하나와 좌표. fontname, size는 pdfplumber 값 그대로 (줄 폰트 진단용)."""

    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    fontname: str = ""
    size: float = 0.0

    @property
    def bbox(self) -> list[float]:
        return [self.x0, self.top, self.x1, self.bottom]


@dataclass
class Segment:
    """가로("h") 또는 세로("v") 선분.

    pos: 선의 위치. h이면 y(top-down), v이면 x.
    start, end: 선이 뻗은 구간. h이면 x0~x1, v이면 top~bottom (start <= end).
    """

    orient: str
    pos: float
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.orient not in ("h", "v"):
            raise ValueError("orient는 'h' 또는 'v'여야 한다")

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class PageGeometry:
    """한 페이지의 선분, 글자, 개체 개수.

    obj_counts: pdfplumber가 인식한 lines/rects/curves 개수 (min_line_length 필터 전).
    작성 프로그램이 표선을 어떻게 그렸는지 추정하는 데 쓴다.
    "thin_images"는 선 조각으로 쓴 얇은 이미지 수이며, cfg.images_as_lines가 꺼져 있으면 키가 없다.
    dash_stats: join_dashes가 남기는 점선 통계 (숫자만, 원문 없음). 계산하지 않았으면 빈 dict.
    obj_types: pdfplumber가 넘겨준 모든 개체의 종류별 개수 (char, line, rect, curve, image 등).
    image_bboxes: 이미지 개체의 bbox 목록. 선이 벡터가 아니라 이미지로 그려졌는지 확인하는 용도.
    """

    page: int
    width: float
    height: float
    segments: list[Segment] = field(default_factory=list)
    chars: list[Char] = field(default_factory=list)
    obj_counts: dict[str, int] = field(default_factory=dict)
    dash_stats: dict[str, Any] = field(default_factory=dict)
    obj_types: dict[str, int] = field(default_factory=dict)
    image_bboxes: list[list[float]] = field(default_factory=list)


def count_pages(pdf_path: str) -> int:
    """PDF의 전체 페이지 수."""
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


# render_page_overlay 색상 (RGBA). 원본 개체는 파랑 얇은 선, 채택 선분은 빨강, 표 bbox는 초록.
_OBJ_COLOR = (0, 0, 255, 160)
_KEPT_COLOR = (255, 0, 0, 220)
_TABLE_COLOR = (0, 160, 0, 255)
_NO_FILL = (0, 0, 0, 0)


def render_page_overlay(
    pdf_path: str,
    page_no: int,
    kept: list[Segment],
    table_bboxes: list[list[float]],
    out_path: str,
    resolution: int = 150,
) -> None:
    """페이지 이미지 위에 선 정보를 겹쳐 PNG로 저장한다 (표가 어떻게 쪼개졌는지 눈으로 보는 용도).

    - 파랑 (얇은 선): 필터 전 원본 개체 전부 (page.lines, page.rects, page.curves, page.images). 버려진 것도 보인다.
      이미지는 선으로 쓰였는지와 무관하게 bbox 사각형으로 그린다.
    - 빨강: 채택된 선분 kept (h이면 (start,pos)-(end,pos), v이면 (pos,start)-(pos,end)).
    - 초록 사각형 테두리: 표 bbox.
    결과 이미지에는 문서 원문이 그대로 나오므로 호출하는 쪽이 저장 위치를 책임진다.
    """
    with pdfplumber.open(pdf_path) as pdf:
        if not 1 <= page_no <= len(pdf.pages):
            raise ValueError("page_no가 PDF 페이지 범위를 벗어났다")
        page = pdf.pages[page_no - 1]
        image = page.to_image(resolution=resolution)

        for line in page.lines:
            image.draw_line(line, stroke=_OBJ_COLOR, stroke_width=1)
        for obj in list(page.rects) + list(page.curves) + list(page.images):
            image.draw_rect(obj, fill=_NO_FILL, stroke=_OBJ_COLOR, stroke_width=1)

        for seg in kept:
            if seg.orient == "h":
                points = [(seg.start, seg.pos), (seg.end, seg.pos)]
            else:
                points = [(seg.pos, seg.start), (seg.pos, seg.end)]
            image.draw_line(points, stroke=_KEPT_COLOR, stroke_width=2)
        for bbox in table_bboxes:
            image.draw_rect(bbox, fill=_NO_FILL, stroke=_TABLE_COLOR, stroke_width=2)

        # quantize=False: 기본 팔레트 축소가 얇은 파랑선 색을 뭉개지 않게 한다
        image.save(out_path, format="PNG", quantize=False)


def rect_to_segments(rect: dict[str, Any], cfg: TableConfig) -> list[Segment]:
    """rect 하나를 선분으로 바꾼다.

    - 얇은 rect (짧은 변이 cfg.thin_rect_max_width 이하): 긴 변 방향의 선분 1개.
      가로로 길면 h, 세로로 길면 v. 위치는 rect 중심선.
    - 일반 rect: 테두리 4개 (위 h, 아래 h, 왼쪽 v, 오른쪽 v 순).
    rect는 pdfplumber 개체 dict(x0, x1, top, bottom)이다.
    min_line_length 필터는 여기서 하지 않는다 (load_page_geometry에서 적용).
    """
    x0 = min(float(rect["x0"]), float(rect["x1"]))
    x1 = max(float(rect["x0"]), float(rect["x1"]))
    top = min(float(rect["top"]), float(rect["bottom"]))
    bottom = max(float(rect["top"]), float(rect["bottom"]))
    width = x1 - x0
    height = bottom - top

    if min(width, height) <= cfg.thin_rect_max_width:
        if width >= height:
            return [Segment("h", (top + bottom) / 2, x0, x1)]
        return [Segment("v", (x0 + x1) / 2, top, bottom)]
    return [
        Segment("h", top, x0, x1),
        Segment("h", bottom, x0, x1),
        Segment("v", x0, top, bottom),
        Segment("v", x1, top, bottom),
    ]


def image_to_segments(image: dict[str, Any], cfg: TableConfig) -> list[Segment]:
    """얇은 이미지 조각 (점선 등) 하나를 선분 1개로 바꾼다. design 6.4절 해석 추가.

    짧은 변이 cfg.thin_rect_max_width 이하인 이미지만 rect_to_segments의 얇은 rect 규칙
    (긴 변 방향 선분 1개, pos는 중심선)을 그대로 쓴다. 그보다 두꺼운 이미지 (사진, 로고)는
    rect처럼 테두리 4개가 되지 않도록 빈 목록을 돌려준다.
    image는 pdfplumber 개체 dict(x0, x1, top, bottom)이다.
    """
    width = abs(float(image["x1"]) - float(image["x0"]))
    height = abs(float(image["bottom"]) - float(image["top"]))
    if min(width, height) > cfg.thin_rect_max_width:
        return []
    return rect_to_segments(image, cfg)


def _line_to_segment(line: dict[str, Any], cfg: TableConfig) -> Segment | None:
    """line 개체를 선분으로 바꾼다. 가로나 세로가 아닌 기울어진 선은 None."""
    x0 = min(float(line["x0"]), float(line["x1"]))
    x1 = max(float(line["x0"]), float(line["x1"]))
    top = min(float(line["top"]), float(line["bottom"]))
    bottom = max(float(line["top"]), float(line["bottom"]))
    dx = x1 - x0
    dy = bottom - top
    if dy <= cfg.snap_tol and dx >= dy:
        return Segment("h", (top + bottom) / 2, x0, x1)
    if dx <= cfg.snap_tol:
        return Segment("v", (x0 + x1) / 2, top, bottom)
    return None


# join_dashes의 gap_hist 구간 폭 (pt)
_GAP_BIN = 0.5
# 부동소수점 오차 흡수용 (pt 비교)
_EPS = 1e-9


def _cluster_by_pos(pieces: list[Segment], tol: float) -> list[list[Segment]]:
    """같은 orient의 조각을 pos 기준으로 묶는다 (single-linkage, tables.cluster_coords와 같은 규칙).

    tables가 extract를 import하므로 순환을 피하려고 여기서 따로 구현한다.
    """
    groups: list[list[Segment]] = []
    for seg in sorted(pieces, key=lambda s: (s.pos, s.start)):
        if groups and seg.pos - groups[-1][-1].pos <= tol:
            groups[-1].append(seg)
        else:
            groups.append([seg])
    return groups


def join_dashes(segments: list[Segment], cfg: TableConfig) -> tuple[list[Segment], dict[str, Any]]:
    """점선처럼 이어진 짧은 조각을 선분 하나로 이어 붙인다 (min_line_length 필터 직전 단계).

    - 길이가 cfg.min_line_length 이상인 선분은 그대로 통과한다.
    - 짧은 조각은 같은 orient이고 pos가 cfg.snap_tol 안에서 이어진 것끼리 묶는다.
    - 묶음 안에서 start 순으로 훑으며, 다음 조각 start와 지금까지 이은 끝의 틈이
      cfg.dash_max_gap 이하이면 이어 붙인다. 이어진 조각이 cfg.dash_min_pieces개 이상이면
      Segment(orient, 이은 조각 pos 평균, 첫 start, 마지막 end) 하나로 만든다.
      조건에 못 미친 조각은 그대로 두므로 이후 min_line_length 필터가 버린다.
    - 반환 순서: 통과한 긴 선분 (입력 순), 이어 붙인 선분, 남은 짧은 조각.

    dash_stats (JSON 직렬화 가능, 숫자만):
      short_pieces: 짧은 조각 수
      runs: 이어 붙인 점선 수
      joined_pieces: 거기 쓰인 조각 수
      gap_hist: 같은 줄 위 연속한 짧은 조각 사이 틈을 0.5pt 단위로 내림한 값 ("0.0", "0.5", ...) -> 개수.
        겹침 (음수 틈)은 "overlap". 조각이 이어졌는지와 무관하게 센다 (dash_max_gap을 정하는 근거).
      max_joined_gap: 이어 붙이는 데 쓰인 틈의 최댓값 (없으면 0.0, 겹침은 0으로 본다)
    """
    long_segs = [s for s in segments if s.length >= cfg.min_line_length]
    shorts = [s for s in segments if s.length < cfg.min_line_length]

    joined: list[Segment] = []
    leftover: list[Segment] = []
    hist: dict[str, int] = {}
    n_runs = 0
    n_joined = 0
    max_joined_gap = 0.0

    def flush(run: list[Segment], run_end: float, run_gap: float) -> None:
        nonlocal n_runs, n_joined, max_joined_gap
        if len(run) >= cfg.dash_min_pieces:
            n_runs += 1
            n_joined += len(run)
            max_joined_gap = max(max_joined_gap, run_gap)
            joined.append(Segment(run[0].orient, sum(s.pos for s in run) / len(run), run[0].start, run_end))
        else:
            leftover.extend(run)

    for orient in ("h", "v"):
        for group in _cluster_by_pos([s for s in shorts if s.orient == orient], cfg.snap_tol):
            pieces = sorted(group, key=lambda s: (s.start, s.end))
            run = [pieces[0]]
            run_end = pieces[0].end
            run_gap = 0.0  # 이 run을 이어 붙이는 데 쓴 틈의 최댓값 (겹침은 0)
            for seg in pieces[1:]:
                gap = seg.start - run_end
                if gap < -_EPS:
                    key = "overlap"
                else:
                    gap = max(gap, 0.0)
                    key = f"{math.floor(gap / _GAP_BIN + _EPS) * _GAP_BIN:.1f}"
                hist[key] = hist.get(key, 0) + 1
                if gap <= cfg.dash_max_gap + _EPS:
                    run_gap = max(run_gap, gap)
                    run.append(seg)
                    run_end = max(run_end, seg.end)
                else:
                    flush(run, run_end, run_gap)
                    run = [seg]
                    run_end = seg.end
                    run_gap = 0.0
            flush(run, run_end, run_gap)

    dash_stats: dict[str, Any] = {
        "short_pieces": len(shorts),
        "runs": n_runs,
        "joined_pieces": n_joined,
        "gap_hist": dict(sorted(hist.items(), key=lambda kv: -1.0 if kv[0] == "overlap" else float(kv[0]))),
        "max_joined_gap": max_joined_gap,
    }
    return long_segs + joined + leftover, dash_stats


def load_page_geometry(pdf_path: str, page_no: int, cfg: TableConfig) -> PageGeometry:
    """한 페이지(1-based)의 선분과 글자를 읽는다.

    pdfplumber의 lines, rects, (cfg.images_as_lines가 켜져 있으면) 얇은 images를 모두 Segment로 바꿔
    candidates에 넣은 뒤, join_dashes로 점선 조각을 이어 붙이고 cfg.min_line_length 미만은 버린다.
    점선 통계는 PageGeometry.dash_stats에 남긴다.
    curves는 선분으로 쓰지 않고 개수만 obj_counts에 남긴다.
    obj_counts["thin_images"]: 선 조각으로 쓴 이미지 수. images_as_lines가 꺼져 있으면 키를 넣지 않는다.
    """
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        if not 1 <= page_no <= n_pages:
            raise ValueError("page_no가 PDF 페이지 범위를 벗어났다")
        page = pdf.pages[page_no - 1]

        candidates: list[Segment] = []
        for line in page.lines:
            seg = _line_to_segment(line, cfg)
            if seg is not None:
                candidates.append(seg)
        for rect in page.rects:
            candidates.extend(rect_to_segments(rect, cfg))
        n_thin_images = 0
        if cfg.images_as_lines:
            for image in page.images:
                segs = image_to_segments(image, cfg)
                n_thin_images += len(segs)
                candidates.extend(segs)
        candidates, dash_stats = join_dashes(candidates, cfg)
        segments = [s for s in candidates if s.length >= cfg.min_line_length]

        chars = [
            Char(
                text=str(c["text"]),
                x0=float(c["x0"]),
                x1=float(c["x1"]),
                top=float(c["top"]),
                bottom=float(c["bottom"]),
                fontname=str(c.get("fontname", "")),
                size=float(c.get("size", 0.0)),
            )
            for c in page.chars
        ]
        obj_counts = {
            "lines": len(page.lines),
            "rects": len(page.rects),
            "curves": len(page.curves),
        }
        if cfg.images_as_lines:
            obj_counts["thin_images"] = n_thin_images
        obj_types = {str(kind): len(objs) for kind, objs in sorted(page.objects.items())}
        image_bboxes = [
            [float(im["x0"]), float(im["top"]), float(im["x1"]), float(im["bottom"])] for im in page.images
        ]
        return PageGeometry(
            page=page_no,
            width=float(page.width),
            height=float(page.height),
            segments=segments,
            chars=chars,
            obj_counts=obj_counts,
            dash_stats=dash_stats,
            obj_types=obj_types,
            image_bboxes=image_bboxes,
        )


def probe_objects(pdf_path: str, page_no: int, box: list[float]) -> dict[str, Any]:
    """box [x0, top, x1, bottom]와 겹치는 모든 개체의 종류, bbox, 그리기 속성 (진단용, 원문 없음).

    글자는 개수만 센다. 반환: {"chars": int, "objects": [{"type", "bbox", "w", "h", "linewidth",
    "stroke", "fill"}]} (bbox의 top, x0 순).
    """
    with pdfplumber.open(pdf_path) as pdf:
        if not 1 <= page_no <= len(pdf.pages):
            raise ValueError("page_no가 PDF 페이지 범위를 벗어났다")
        page = pdf.pages[page_no - 1]
        n_chars = 0
        found: list[dict[str, Any]] = []
        for kind, objs in page.objects.items():
            for o in objs:
                x0, top, x1, bottom = float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"])
                if x1 < box[0] or x0 > box[2] or bottom < box[1] or top > box[3]:
                    continue
                if kind == "char":
                    n_chars += 1
                    continue
                found.append(
                    {
                        "type": str(kind),
                        "bbox": [x0, top, x1, bottom],
                        "w": x1 - x0,
                        "h": bottom - top,
                        "linewidth": o.get("linewidth"),
                        "stroke": o.get("stroke"),
                        "fill": o.get("fill"),
                    }
                )
        found.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))
        return {"chars": n_chars, "objects": found}
