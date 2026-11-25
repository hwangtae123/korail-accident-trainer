"""표 격자, region, 셀 병합, 글자 배정, header, 레코드, HTML, 자체 검사, 주석 연결
(design.md 6.4절 1단계).

대부분 선분(Segment)과 글자(Char)만 입력으로 받는 순수 함수 모음이다. pdfplumber는 직접
import하지 않는다 (PDF를 여는 것은 extract 모듈이며, parse_pdf_tables만 그것을 호출한다).
좌표는 top-down, 단위는 pt. 예외 메시지에는 문서 내용을 넣지 않는다.

이 모듈에는 표의 크기(열 수, 행 수)나 header 줄 수 같은 상수를 두지 않는다.
"""

import html
import re
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field, replace
from typing import Any

from policy_rag.config import TableConfig
from policy_rag.ingest.extract import Char, PageGeometry, Segment, count_pages, load_page_geometry

# 파서 버전. 산출물(캐시, 리포트)이 어느 파서로 만들어졌는지 구분하는 데 쓴다.
# 0.2: 접두어 바로 뒤가 번호인 주석을 번호 항목 ("㈜ 1. … 2. …")으로 나눔
PARSER_VERSION = "table-0.2"

# 부동소수점 오차 흡수용 (pt 또는 비율 비교)
_EPS = 1e-9


# --------------------------------------------------------------------------
# 데이터 구조
# --------------------------------------------------------------------------

@dataclass
class TableRegion:
    """표 후보 영역. 서로 연결된 선분 묶음 하나.

    page: 1-based 페이지 번호.
    bbox: [x0, top, x1, bottom], 묶음에 속한 선분 전체를 감싸는 상자.
    segment_ids: find_table_regions에 넘긴 segments 목록의 인덱스 (오름차순).
    """

    page: int
    bbox: list[float]
    segment_ids: list[int]


@dataclass
class Grid:
    """격자 좌표. xs는 세로 격자선의 x, ys는 가로 격자선의 y (모두 오름차순 대표값).

    snap_tol: 좌표를 묶을 때 쓴 허용 오차.
    n_raw_xs, n_raw_ys: 묶기 전 좌표 개수 (선분 개수 기준, 중복 포함). 리포트용.
    max_shift: 묶기 전 좌표가 대표값으로 옮겨진 거리의 최댓값 (x, y 통틀어). 리포트용.
    """

    xs: list[float]
    ys: list[float]
    snap_tol: float
    n_raw_xs: int = 0
    n_raw_ys: int = 0
    max_shift: float = 0.0

    @property
    def n_rows(self) -> int:
        return max(len(self.ys) - 1, 0)

    @property
    def n_cols(self) -> int:
        return max(len(self.xs) - 1, 0)


@dataclass
class EdgeFlags:
    """격자 단위 구간마다 선이 있는지.

    h[i][c]: i번째 가로 격자선의 c번째 열 구간 (i: 0..n_rows, c: 0..n_cols-1).
    v[r][j]: j번째 세로 격자선의 r번째 행 구간 (r: 0..n_rows-1, j: 0..n_cols).
    격자에 행 또는 열이 없으면 둘 다 빈 리스트.
    """

    h: list[list[bool]]
    v: list[list[bool]]


@dataclass
class Cell:
    """격자 (row, col)에서 시작해 rowspan x colspan 칸을 덮는 셀.

    bbox는 grid 좌표 기준 [x0, top, x1, bottom].
    text, char_ids, is_header는 이후 단계(글자 배정, header 판정)에서 채운다.
    """

    row: int
    col: int
    rowspan: int
    colspan: int
    bbox: list[float]
    text: str = ""
    char_ids: list[int] = field(default_factory=list)
    is_header: bool = False


# --------------------------------------------------------------------------
# 좌표 묶기
# --------------------------------------------------------------------------

def cluster_coords(values: list[float], tol: float) -> list[float]:
    """가까운 좌표를 묶어 대표값(평균) 목록을 오름차순으로 반환한다.

    정렬 후 인접 값의 간격이 tol 이하이면 같은 묶음이다 (single-linkage).
    그래서 간격이 tol 이하인 값이 이어지면 전체 폭이 tol을 넘어도 한 묶음이 된다.
    """
    if tol < 0:
        raise ValueError("tol은 0 이상이어야 한다")
    if not values:
        return []
    ordered = sorted(values)
    centers: list[float] = []
    group = [ordered[0]]
    for value in ordered[1:]:
        if value - group[-1] <= tol:
            group.append(value)
        else:
            centers.append(sum(group) / len(group))
            group = [value]
    centers.append(sum(group) / len(group))
    return centers


def snap_to(value: float, centers: list[float]) -> int:
    """value에 가장 가까운 대표값의 인덱스. centers는 오름차순이어야 한다.

    같은 거리이면 작은 쪽(앞 인덱스)을 고른다.
    """
    if not centers:
        raise ValueError("centers가 비어 있다")
    i = bisect_left(centers, value)
    if i == 0:
        return 0
    if i == len(centers):
        return len(centers) - 1
    before = centers[i - 1]
    after = centers[i]
    return i - 1 if value - before <= after - value else i


def _max_shift(values: list[float], centers: list[float]) -> float:
    if not values or not centers:
        return 0.0
    return max(abs(v - centers[snap_to(v, centers)]) for v in values)


# --------------------------------------------------------------------------
# 표 후보 영역
# --------------------------------------------------------------------------

def _find(parent: list[int], i: int) -> int:
    """union-find의 root (경로 압축)."""
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def _union(parent: list[int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[max(ra, rb)] = min(ra, rb)


def _segments_touch(a: Segment, b: Segment, tol: float) -> bool:
    """두 선분이 교차하거나 겹치는지 (끝점 tol 포함)."""
    if a.orient != b.orient:
        h, v = (a, b) if a.orient == "h" else (b, a)
        return (
            h.start - tol <= v.pos <= h.end + tol
            and v.start - tol <= h.pos <= v.end + tol
        )
    # 같은 방향: 거의 같은 선 위에서 구간이 이어지거나 겹칠 때
    return abs(a.pos - b.pos) <= tol and a.start <= b.end + tol and b.start <= a.end + tol


def find_table_regions(segments: list[Segment], cfg: TableConfig, page: int) -> list[TableRegion]:
    """선분 연결 성분 중 표 후보를 찾는다.

    서로 교차하거나 겹치는 선분끼리 한 성분으로 묶고, 가로선과 세로선이 각각 2개 이상인
    성분만 표 후보로 남긴다. 밑줄(가로선 단독)이나 선 없는 표는 후보가 되지 않는다.
    결과는 위에서 아래, 왼쪽에서 오른쪽 순 (bbox의 top, x0 기준).
    """
    n = len(segments)
    if n == 0:
        return []
    tol = cfg.snap_tol
    parent = list(range(n))

    hs = [i for i in range(n) if segments[i].orient == "h"]
    vs = [i for i in range(n) if segments[i].orient == "v"]
    for i in hs:
        for j in vs:
            if _segments_touch(segments[i], segments[j], tol):
                _union(parent, i, j)
    # 같은 방향끼리는 pos로 정렬해 tol 이내 이웃만 비교한다
    for group in (hs, vs):
        ordered = sorted(group, key=lambda k: segments[k].pos)
        for a_pos, a in enumerate(ordered):
            for b in ordered[a_pos + 1:]:
                if segments[b].pos - segments[a].pos > tol:
                    break
                if _segments_touch(segments[a], segments[b], tol):
                    _union(parent, a, b)

    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(_find(parent, i), []).append(i)

    regions: list[TableRegion] = []
    for ids in components.values():
        n_h = sum(1 for i in ids if segments[i].orient == "h")
        n_v = len(ids) - n_h
        if n_h < 2 or n_v < 2:
            continue
        members = [segments[i] for i in ids]
        x0 = min(s.start if s.orient == "h" else s.pos for s in members)
        x1 = max(s.end if s.orient == "h" else s.pos for s in members)
        top = min(s.pos if s.orient == "h" else s.start for s in members)
        bottom = max(s.pos if s.orient == "h" else s.end for s in members)
        regions.append(TableRegion(page=page, bbox=[x0, top, x1, bottom], segment_ids=sorted(ids)))
    regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
    return regions


# --------------------------------------------------------------------------
# 격자, 경계선 유무, 셀
# --------------------------------------------------------------------------

def _region_segments(segments: list[Segment], region: TableRegion) -> list[Segment]:
    """region에 속한 선분만 골라 반환한다."""
    try:
        return [segments[i] for i in region.segment_ids]
    except IndexError:
        raise ValueError("region.segment_ids가 segments 범위를 벗어났다") from None


def build_grid(segments: list[Segment], region: TableRegion, cfg: TableConfig) -> Grid:
    """region의 세로선 x와 가로선 y를 각각 묶어 격자 좌표를 만든다."""
    segs = _region_segments(segments, region)
    raw_xs = [s.pos for s in segs if s.orient == "v"]
    raw_ys = [s.pos for s in segs if s.orient == "h"]
    xs = cluster_coords(raw_xs, cfg.snap_tol)
    ys = cluster_coords(raw_ys, cfg.snap_tol)
    return Grid(
        xs=xs,
        ys=ys,
        snap_tol=cfg.snap_tol,
        n_raw_xs=len(raw_xs),
        n_raw_ys=len(raw_ys),
        max_shift=max(_max_shift(raw_xs, xs), _max_shift(raw_ys, ys)),
    )


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """겹치거나 맞닿은 구간을 합친다."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _covered_length(merged: list[tuple[float, float]], lo: float, hi: float) -> float:
    """합쳐진 구간들이 [lo, hi]를 덮는 길이."""
    total = 0.0
    for start, end in merged:
        if end <= lo:
            continue
        if start >= hi:
            break
        total += min(end, hi) - max(start, lo)
    return total


def _edge_row(
    merged: list[tuple[float, float]] | None, bounds: list[float], min_coverage: float
) -> list[bool]:
    """한 격자선 위의 구간별 선 유무. bounds는 그 선과 직교하는 방향의 격자 좌표."""
    flags: list[bool] = []
    for lo, hi in zip(bounds, bounds[1:]):
        if merged is None:
            flags.append(False)
            continue
        length = hi - lo
        flags.append(_covered_length(merged, lo, hi) >= min_coverage * length - _EPS)
    return flags


def build_edge_flags(
    grid: Grid, segments: list[Segment], region: TableRegion, cfg: TableConfig
) -> EdgeFlags:
    """격자 단위 구간마다 선이 있는지 계산한다.

    선분의 pos를 snap_to로 가장 가까운 격자선에 배정하고, 같은 격자선에 놓인 선분들의
    합집합이 구간 길이의 cfg.line_min_coverage 이상을 덮으면 True다.
    선분 양 끝은 cfg.snap_tol만큼 늘려서 본다 (끝점 어긋남과 조각 사이 작은 틈 흡수).
    중복된 선분은 합집합이라 결과에 영향이 없다.
    """
    if grid.n_rows == 0 or grid.n_cols == 0:
        return EdgeFlags(h=[], v=[])
    segs = _region_segments(segments, region)
    tol = cfg.snap_tol

    h_groups: dict[int, list[tuple[float, float]]] = {}
    v_groups: dict[int, list[tuple[float, float]]] = {}
    for s in segs:
        if s.orient == "h":
            h_groups.setdefault(snap_to(s.pos, grid.ys), []).append((s.start - tol, s.end + tol))
        else:
            v_groups.setdefault(snap_to(s.pos, grid.xs), []).append((s.start - tol, s.end + tol))
    h_merged = {i: _merge_intervals(iv) for i, iv in h_groups.items()}
    v_merged = {j: _merge_intervals(iv) for j, iv in v_groups.items()}

    cov = cfg.line_min_coverage
    h = [_edge_row(h_merged.get(i), grid.xs, cov) for i in range(grid.n_rows + 1)]
    # v[r][j]: 세로선 j의 행 r 구간. 세로선 기준으로 계산한 뒤 전치한다.
    v_by_line = [_edge_row(v_merged.get(j), grid.ys, cov) for j in range(grid.n_cols + 1)]
    v = [[v_by_line[j][r] for j in range(grid.n_cols + 1)] for r in range(grid.n_rows)]
    return EdgeFlags(h=h, v=v)


def build_cells(grid: Grid, flags: EdgeFlags) -> list[Cell]:
    """사이에 선이 없는 인접 칸을 묶어 셀 목록을 만든다 (row, col 순).

    각 묶음의 행/열 범위가 rowspan/colspan이 된다. 묶음이 직사각형이 아니어도
    예외 없이 bounding 범위로 Cell을 만든다 (겹침은 이후 자체 검사가 잡는다).
    """
    n_rows, n_cols = grid.n_rows, grid.n_cols
    if n_rows == 0 or n_cols == 0:
        return []
    if (
        len(flags.h) != n_rows + 1
        or len(flags.v) != n_rows
        or any(len(row) != n_cols for row in flags.h)
        or any(len(row) != n_cols + 1 for row in flags.v)
    ):
        raise ValueError("flags 크기가 grid와 맞지 않는다")

    parent = list(range(n_rows * n_cols))
    for r in range(n_rows):
        for c in range(n_cols):
            here = r * n_cols + c
            if c + 1 < n_cols and not flags.v[r][c + 1]:
                _union(parent, here, here + 1)
            if r + 1 < n_rows and not flags.h[r + 1][c]:
                _union(parent, here, here + n_cols)

    spans: dict[int, list[int]] = {}  # root -> [min_row, min_col, max_row, max_col]
    for r in range(n_rows):
        for c in range(n_cols):
            root = _find(parent, r * n_cols + c)
            if root not in spans:
                spans[root] = [r, c, r, c]
            else:
                s = spans[root]
                s[0], s[1] = min(s[0], r), min(s[1], c)
                s[2], s[3] = max(s[2], r), max(s[3], c)

    cells = [
        Cell(
            row=r0,
            col=c0,
            rowspan=r1 - r0 + 1,
            colspan=c1 - c0 + 1,
            bbox=[grid.xs[c0], grid.ys[r0], grid.xs[c1 + 1], grid.ys[r1 + 1]],
        )
        for r0, c0, r1, c1 in spans.values()
    ]
    cells.sort(key=lambda cell: (cell.row, cell.col, cell.rowspan, cell.colspan))
    return cells


# --------------------------------------------------------------------------
# 글자 배정, header, 열 이름, 레코드, HTML (design.md 6.4절 1단계의 3~4, 6번)
# --------------------------------------------------------------------------

@dataclass
class RowRecord:
    """본문 한 행의 레코드 (병합을 풀고 값을 채운 형태).

    row: 격자 행 인덱스 (header 행을 포함한 표 전체 기준).
    values[c]: (row, c)를 덮는 셀의 text. 덮는 셀이 없으면 빈 문자열.
    filled[c]: 그 값이 병합 채움으로 들어왔는지 ((row, c)가 그 셀의 시작 칸이 아님).
    세로 병합과 본문 가로 병합 모두 True가 된다.
    """

    row: int
    values: list[str]
    filled: list[bool]


def _clone_cell(cell: Cell, **changes: Any) -> Cell:
    """Cell의 복사본 (list 필드까지 새로 만든다). changes로 필드를 바꿀 수 있다."""
    fields_ = {"bbox": list(cell.bbox), "char_ids": list(cell.char_ids)}
    fields_.update(changes)
    return replace(cell, **fields_)


def _locate(edges: list[float], value: float) -> int | None:
    """value가 놓인 칸 인덱스. edges는 오름차순 격자선 좌표.

    격자선 위에 정확히 놓이면 뒤쪽(오른쪽, 아래쪽) 칸에 속한다. 마지막 선 위는 마지막 칸이다.
    격자 밖이면 None.
    """
    if len(edges) < 2 or value < edges[0] or value > edges[-1]:
        return None
    return min(bisect_right(edges, value) - 1, len(edges) - 2)


def _cover_map(cells: list[Cell], grid: Grid) -> dict[tuple[int, int], int]:
    """격자 칸 (row, col) -> 그 칸을 덮는 셀의 인덱스 (cells 목록 기준).

    격자 밖으로 나간 부분은 무시한다. 여러 셀이 같은 칸을 덮으면 목록에서 앞선 셀이 우선이다
    (겹침은 check_grid의 몫).
    """
    covered: dict[tuple[int, int], int] = {}
    for i, cell in enumerate(cells):
        for r in range(max(cell.row, 0), min(cell.row + cell.rowspan, grid.n_rows)):
            for c in range(max(cell.col, 0), min(cell.col + cell.colspan, grid.n_cols)):
                covered.setdefault((r, c), i)
    return covered


def _group_lines(chars: list[Char]) -> list[list[Char]]:
    """글자를 줄로 묶는다 (위에서 아래 순, 줄 안은 x0 순).

    묶는 기준: 세로 중심(cy) 순으로 훑으며, 현재 줄의 평균 cy보다 0.5 * (줄 안 최소 글자
    높이) 넘게 아래에 있는 글자에서 새 줄을 시작한다. 글자 높이는 폰트 크기를 따라가므로
    수치 상수 없이 글자 크기에 맞춰진다. 높이가 0 이하인 글자는 최소 높이 계산에서 뺀다
    (모두 그렇다면 cy가 정확히 같은 글자끼리만 한 줄).
    """
    if not chars:
        return []
    ordered = sorted(chars, key=lambda ch: ((ch.top + ch.bottom) / 2, ch.x0))
    lines: list[list[Char]] = []
    sum_cy = 0.0
    min_h: float | None = None
    for ch in ordered:
        cy = (ch.top + ch.bottom) / 2
        height = ch.bottom - ch.top
        if lines:
            cand = min_h
            if height > 0:
                cand = height if cand is None else min(cand, height)
            threshold = 0.5 * cand if cand is not None else 0.0
            if cy - sum_cy / len(lines[-1]) <= threshold + _EPS:
                lines[-1].append(ch)
                sum_cy += cy
                min_h = cand
                continue
        lines.append([ch])
        sum_cy = cy
        min_h = height if height > 0 else None
    return [sorted(line, key=lambda ch: ch.x0) for line in lines]


def _cell_text(chars: list[Char], cfg: TableConfig) -> str:
    """셀 안 글자들로 text를 만든다.

    줄 안은 x0 순으로 이어 붙이고, 줄 사이는 cfg.cell_line_join으로 잇는다.
    공백 글자는 그대로 두되 공백뿐인 줄은 버리고, 전체 양끝 공백은 strip한다.
    """
    lines = ["".join(ch.text for ch in line) for line in _group_lines(chars)]
    lines = [line for line in lines if line.strip()]
    return cfg.cell_line_join.join(lines).strip()


def assign_chars(
    cells: list[Cell], grid: Grid, chars: list[Char], region: TableRegion, cfg: TableConfig
) -> list[Cell]:
    """글자 중심 좌표로 글자를 셀에 배정한 새 셀 목록을 반환한다 (입력은 변형하지 않는다).

    - region.bbox를 cfg.snap_tol만큼 넓힌 상자 안에 중심이 있는 글자만 대상이다.
    - 중심 좌표가 놓인 격자 칸을 덮는 셀의 char_ids에 chars 목록의 인덱스를 추가한다.
      한 셀이 여러 칸을 덮으면 그 칸들의 글자가 모두 그 셀로 모인다.
    - 어느 셀에도 못 들어간 글자 (격자 밖, 덮는 셀 없음)는 제외한다. 보고는 check_chars의 몫.
    - 입력 셀의 text와 char_ids는 무시하고 새로 계산한다.
    """
    result = [_clone_cell(cell, text="", char_ids=[]) for cell in cells]
    if grid.n_rows == 0 or grid.n_cols == 0 or not chars:
        return result

    covered = _cover_map(cells, grid)
    tol = cfg.snap_tol
    x0, top, x1, bottom = region.bbox
    for idx, ch in enumerate(chars):
        cx = (ch.x0 + ch.x1) / 2
        cy = (ch.top + ch.bottom) / 2
        if not (x0 - tol <= cx <= x1 + tol and top - tol <= cy <= bottom + tol):
            continue
        col = _locate(grid.xs, cx)
        row = _locate(grid.ys, cy)
        if col is None or row is None:
            continue
        cell_idx = covered.get((row, col))
        if cell_idx is not None:
            result[cell_idx].char_ids.append(idx)

    for cell in result:
        cell.text = _cell_text([chars[i] for i in cell.char_ids], cfg)
    return result


def find_header_end(grid: Grid, flags: EdgeFlags) -> int:
    """처음으로 표 전체를 가로지르는 내부 가로선의 행 인덱스 (= header 줄 수).

    내부 가로선 r=1..n_rows-1 중 flags.h[r]이 모두 True인 첫 r. 없으면 0.
    """
    for r in range(1, grid.n_rows):
        if r < len(flags.h) and flags.h[r] and all(flags.h[r]):
            return r
    return 0


def mark_header(cells: list[Cell], header_rows: int) -> list[Cell]:
    """row < header_rows인 셀만 is_header=True인 새 셀 목록을 반환한다 (입력 불변)."""
    return [_clone_cell(cell, is_header=cell.row < header_rows) for cell in cells]


def build_columns(cells: list[Cell], grid: Grid, header_rows: int, cfg: TableConfig) -> list[str]:
    """열 이름을 만든다.

    열마다 header 행을 위에서 아래로 훑어 그 열을 덮는 셀을 (중복 없이) 모으고, text를
    cfg.header_join으로 잇는다. 3단 이상 header도 같은 방식이다. text가 빈 셀은 경로에서
    건너뛴다. header_rows가 0이면 빈 문자열 n_cols개.

    번호 규칙: header 셀 하나가 여러 열을 덮어 (colspan) 열 이름이 겹치면, 두 번째 열부터
    이름 뒤에 "(k)"를 붙인다 (k = 같은 header 셀 경로가 나온 순번, 2부터). 예: "X", "X(2)".
    같은 경로인지는 열이 덮이는 header 셀 인덱스 목록이 같은지로 판정한다. 서로 다른 셀이
    우연히 같은 글자인 경우는 번호를 붙이지 않는다 (호출자의 DUP_COLUMN_NAME 경고 몫).
    이름이 빈 열 (header 글자 없음)에도 붙이지 않는다.
    """
    covered = _cover_map(cells, grid)
    columns: list[str] = []
    path_counts: dict[tuple[int, ...], int] = {}  # header 셀 경로 -> 지금까지 나온 횟수
    for c in range(grid.n_cols):
        seen: list[int] = []
        path: list[str] = []
        for r in range(min(max(header_rows, 0), grid.n_rows)):
            idx = covered.get((r, c))
            if idx is None or idx in seen:
                continue
            seen.append(idx)
            if cells[idx].text.strip():
                path.append(cells[idx].text)
        name = cfg.header_join.join(path)
        key = tuple(seen)
        path_counts[key] = path_counts.get(key, 0) + 1
        if name and path_counts[key] >= 2:
            name = f"{name}({path_counts[key]})"
        columns.append(name)
    return columns


def build_records(cells: list[Cell], grid: Grid, header_rows: int) -> list[RowRecord]:
    """본문 각 행의 레코드를 만든다 (병합을 풀고 덮는 모든 칸에 값을 채운다)."""
    covered = _cover_map(cells, grid)
    records: list[RowRecord] = []
    for r in range(min(max(header_rows, 0), grid.n_rows), grid.n_rows):
        values: list[str] = []
        filled: list[bool] = []
        for c in range(grid.n_cols):
            idx = covered.get((r, c))
            if idx is None:
                values.append("")
                filled.append(False)
                continue
            cell = cells[idx]
            values.append(cell.text)
            filled.append((cell.row, cell.col) != (r, c))
        records.append(RowRecord(row=r, values=values, filled=filled))
    return records


def to_html(cells: list[Cell], header_rows: int) -> str:
    """rowspan/colspan을 유지한 HTML 표를 만든다 (같은 입력이면 같은 문자열).

    header_rows > 0이면 그 행들은 <thead>의 <th>, 나머지는 <tbody>의 <td>.
    셀은 시작 행에서 한 번만 출력하고, span은 1을 넘을 때만 속성으로 붙인다.
    다른 셀에 덮여 시작 셀이 없는 행도 빈 <tr>로 남긴다 (rowspan이 성립하도록).
    text는 html.escape로 처리한다. 한 줄에 <tr> 하나, 들여쓰기 없음.
    """
    if not cells:
        return "<table>\n</table>"
    n_rows = max(cell.row + cell.rowspan for cell in cells)
    by_row: dict[int, list[Cell]] = {}
    for cell in cells:
        by_row.setdefault(cell.row, []).append(cell)

    def render_row(r: int, tag: str) -> str:
        parts: list[str] = []
        for cell in sorted(by_row.get(r, []), key=lambda x: (x.col, x.colspan, x.rowspan)):
            attrs = ""
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            parts.append(f"<{tag}{attrs}>{html.escape(cell.text)}</{tag}>")
        return "<tr>" + "".join(parts) + "</tr>"

    n_head = min(max(header_rows, 0), n_rows)
    lines = ["<table>"]
    if n_head > 0:
        lines.append("<thead>")
        lines += [render_row(r, "th") for r in range(n_head)]
        lines.append("</thead>")
    if n_head < n_rows:
        lines.append("<tbody>")
        lines += [render_row(r, "td") for r in range(n_head, n_rows)]
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 자체 검사 (design.md 6.4절 1단계의 5번)
# --------------------------------------------------------------------------

@dataclass
class GridCheck:
    """격자 일관성 검사 결과. 위치는 모두 [row, col] (격자 칸 또는 셀 시작 칸).

    overlaps: 두 셀 이상이 덮는 격자 칸.
    gaps: 어느 셀도 덮지 않는 격자 칸.
    non_rect: 격자 밖으로 나가거나, 범위 안에 경계선이 있는 (직사각형이 아닌 병합) 셀의 시작 칸.
    """

    ok: bool
    overlaps: list[list[int]] = field(default_factory=list)
    gaps: list[list[int]] = field(default_factory=list)
    non_rect: list[list[int]] = field(default_factory=list)


@dataclass
class CharCheck:
    """글자 보존 검사 결과. 글자 위치는 PageGeometry.chars의 인덱스. 공백 글자는 검사에서 제외한다.

    n_in_bbox: 표 영역(region.bbox, snap_tol 포함) 안에 중심이 있는 글자 수.
    n_assigned: 그중 셀에 배정된 글자 수 (한 번 이상).
    unassigned: 영역 안인데 어느 셀에도 배정되지 않은 글자.
    multi_assigned: 둘 이상의 셀에 배정된 글자.
    straddling: 글자 상자가 배정된 셀 경계를 snap_tol 넘게 벗어난 글자.
    """

    ok: bool
    n_in_bbox: int = 0
    n_assigned: int = 0
    unassigned: list[int] = field(default_factory=list)
    multi_assigned: list[int] = field(default_factory=list)
    straddling: list[int] = field(default_factory=list)


def check_grid(grid: Grid, cells: list[Cell], flags: EdgeFlags | None = None) -> GridCheck:
    """셀들이 격자를 겹침과 빈틈 없이 채우는지 검사한다.

    셀 목록만으로 격자 칸별 덮은 횟수를 세어 0회는 gaps, 2회 이상은 overlaps로 보고한다.
    non_rect는 셀 목록만으로는 알 수 없다: build_cells는 직사각형이 아닌 묶음도 bounding
    범위로 만들어 버리기 때문이다. 그래서 flags를 받으면 "셀 범위 안쪽에 경계선이 있는 셀"
    (= 병합이 직사각형이 아니라는 뜻)과 격자 밖으로 나간 셀을 non_rect로 보고한다.
    flags가 None이면 격자 밖으로 나간 셀만 non_rect에 들어간다.
    """
    n_rows, n_cols = grid.n_rows, grid.n_cols
    counts = [[0] * n_cols for _ in range(n_rows)]
    non_rect: list[list[int]] = []
    for cell in cells:
        r_end, c_end = cell.row + cell.rowspan, cell.col + cell.colspan
        bad = cell.row < 0 or cell.col < 0 or r_end > n_rows or c_end > n_cols
        for r in range(max(cell.row, 0), min(r_end, n_rows)):
            for c in range(max(cell.col, 0), min(c_end, n_cols)):
                counts[r][c] += 1
        if flags is not None and not bad:
            inner_h = any(
                flags.h[r][c]
                for r in range(cell.row + 1, r_end)
                for c in range(cell.col, c_end)
                if r < len(flags.h) and c < len(flags.h[r])
            )
            inner_v = any(
                flags.v[r][c]
                for r in range(cell.row, r_end)
                for c in range(cell.col + 1, c_end)
                if r < len(flags.v) and c < len(flags.v[r])
            )
            bad = inner_h or inner_v
        if bad:
            non_rect.append([cell.row, cell.col])

    overlaps = [[r, c] for r in range(n_rows) for c in range(n_cols) if counts[r][c] >= 2]
    gaps = [[r, c] for r in range(n_rows) for c in range(n_cols) if counts[r][c] == 0]
    return GridCheck(ok=not (overlaps or gaps or non_rect), overlaps=overlaps, gaps=gaps, non_rect=non_rect)


def check_chars(
    cells: list[Cell], chars: list[Char], region: TableRegion, grid: Grid, cfg: TableConfig
) -> CharCheck:
    """표 영역의 모든 글자가 정확히 한 셀에 배정됐는지 검사한다 (공백 글자는 제외).

    영역은 assign_chars와 같이 region.bbox를 cfg.snap_tol만큼 넓힌 상자이고, 글자는 중심 좌표로
    판단한다. straddling은 배정된 셀의 경계 (grid 좌표로 다시 계산)를 snap_tol 넘게 벗어난 글자다.
    """
    tol = cfg.snap_tol
    x0, top, x1, bottom = region.bbox
    in_bbox: set[int] = set()
    for idx, ch in enumerate(chars):
        if ch.text.isspace():
            continue
        cx = (ch.x0 + ch.x1) / 2
        cy = (ch.top + ch.bottom) / 2
        if x0 - tol <= cx <= x1 + tol and top - tol <= cy <= bottom + tol:
            in_bbox.add(idx)

    times: dict[int, int] = {}
    straddling: set[int] = set()
    for cell in cells:
        in_grid = (
            0 <= cell.col and cell.col + cell.colspan < len(grid.xs)
            and 0 <= cell.row and cell.row + cell.rowspan < len(grid.ys)
        )
        if in_grid:
            cx0, cx1 = grid.xs[cell.col], grid.xs[cell.col + cell.colspan]
            cy0, cy1 = grid.ys[cell.row], grid.ys[cell.row + cell.rowspan]
        else:  # 격자 밖으로 나간 셀은 저장된 bbox를 쓴다 (check_grid가 따로 보고한다)
            cx0, cy0, cx1, cy1 = cell.bbox
        for idx in cell.char_ids:
            if idx not in in_bbox:
                continue
            times[idx] = times.get(idx, 0) + 1
            ch = chars[idx]
            if ch.x0 < cx0 - tol or ch.x1 > cx1 + tol or ch.top < cy0 - tol or ch.bottom > cy1 + tol:
                straddling.add(idx)

    unassigned = sorted(in_bbox - set(times))
    multi = sorted(i for i, n in times.items() if n >= 2)
    return CharCheck(
        ok=not (unassigned or multi or straddling),
        n_in_bbox=len(in_bbox),
        n_assigned=len(times),
        unassigned=unassigned,
        multi_assigned=multi,
        straddling=sorted(straddling),
    )


# --------------------------------------------------------------------------
# (주) 주석 연결 (design.md 6.3절 주석 처리)
# --------------------------------------------------------------------------

def attach_notes(
    table_bbox: list[float], chars: list[Char], next_table_top: float | None, cfg: TableConfig
) -> list[str]:
    """표 바로 아래의 주석 항목 목록을 만든다 (표 밖 글자만 대상).

    줄을 찾는 규칙은 _note_lines, 항목으로 잇는 규칙은 _join_notes, 번호 항목으로 나누는 규칙은 _split_note에 있다.
    parse_table은 notes_bottom 때문에 _note_lines와 _join_notes를 직접 부른다 (같은 규칙).
    """
    return _join_notes(_note_lines(table_bbox, chars, next_table_top, cfg), cfg.note_prefixes)


# 주석 번호 형태: "N." (뒤가 숫자면 소수라 아님), "(N)", 원문자 (①~⑳)
_NOTE_NUMBER_PATTERNS = (
    re.compile(r"(?<!\d)(\d+)\.(?!\d)"),
    re.compile(r"\((\d+)\)"),
    re.compile(r"([①-⑳])"),
)
# 앞 문장이 끝났다고 보는 글자 (번호 바로 앞의 공백 아닌 글자)
_SENTENCE_ENDS = ".。!?"


def _note_number(m: re.Match[str]) -> int:
    value = m.group(1)
    return int(value) if value.isascii() else ord(value) - 0x2460 + 1


def _split_note(note: str, note_prefixes: list[str]) -> list[str]:
    """접두어 바로 뒤가 번호로 시작하는 주석을 번호 항목으로 나눈다. 아니면 [note].

    이후 같은 형태 번호가 1씩 이어지고 바로 앞 공백 아닌 글자가 문장 끝 (_SENTENCE_ENDS)일 때만 나눈다
    ("2.의 경우"처럼 문장 중간이면 나누지 않는다). 접두어는 NFKC로 비교하고, 나눈 조각은 원문 그대로 (양끝 공백만 정리).
    """
    prefixes = tuple(unicodedata.normalize("NFKC", p) for p in note_prefixes)
    end = next(
        (k for k in range(1, len(note) + 1) if unicodedata.normalize("NFKC", note[:k]).startswith(prefixes)), None
    )
    if end is None:
        return [note]
    start = end + len(note[end:]) - len(note[end:].lstrip())
    for pattern in _NOTE_NUMBER_PATTERNS:
        first = pattern.match(note, start)
        if first is not None:
            break
    else:
        return [note]
    cuts: list[int] = []
    expected = _note_number(first) + 1
    for m in pattern.finditer(note, first.end()):
        before = note[:m.start()].rstrip()
        if _note_number(m) == expected and before[-1:] in tuple(_SENTENCE_ENDS):
            cuts.append(m.start())
            expected += 1
    bounds = [0, *cuts, len(note)]
    return [note[a:b].strip() for a, b in zip(bounds, bounds[1:])]


def _join_notes(lines: list[tuple[float, float, str, bool]], note_prefixes: list[str]) -> list[str]:
    """주석 줄 (top, bottom, text, 항목 시작 여부)을 항목으로 잇는다. 항목 안의 줄은 공백 1개로 잇는다.
    이은 항목은 _split_note로 번호 항목마다 나눈다 (attach_notes와 parse_table이 함께 쓴다)."""
    notes: list[str] = []
    for _top, _bottom, text, is_start in lines:
        if is_start or not notes:
            notes.append(text)
        else:
            notes[-1] += " " + text
    return [part for note in notes for part in _split_note(note, note_prefixes)]


def _note_lines(
    table_bbox: list[float], chars: list[Char], next_table_top: float | None, cfg: TableConfig
) -> list[tuple[float, float, str, bool]]:
    """표 바로 아래의 주석 줄 목록 (top, bottom, text, 항목 시작 여부). 주석이 없으면 빈 리스트.

    - 대상 글자: 중심이 table_bbox 아래 (bottom + snap_tol 초과), 다음 표 위 (next_table_top -
      snap_tol 미만, None이면 페이지 끝까지)에 있는 글자. 표 안 글자를 배정하는 assign_chars의
      경계와 맞물리게 snap_tol만큼 띄운다. x 범위는 제한하지 않는다.
    - 대상 글자를 _group_lines로 줄로 묶는다. 공백 글자뿐인 줄 (strip 후 빈 줄)은 없는 것으로 보고
      건너뛴다. 표 바로 아래 "첫 줄"은 건너뛰고 남은 첫 실제 줄이다.
    - 그 첫 줄이 cfg.note_prefixes 중 하나로 시작할 때만 주석이 시작된다. 아니면 빈 리스트.
      시작 여부는 NFKC 정규화한 줄과 정규화한 접두어를 비교한다 (호환 문자 "㈜"는 "(주)"로 본다).
      정규화는 비교에만 쓰고, 반환하는 주석 텍스트는 원문 그대로다.
    - 표 bottom -> 첫 실제 줄 top, 앞 실제 줄 bottom -> 다음 실제 줄 top 간격이 cfg.note_max_gap
      이하인 동안 줄을 잇는다 (건너뛴 공백 줄의 높이도 간격에 포함된다). 접두어로 시작하는
      줄은 새 항목이고, 한 항목 안의 줄은 공백 1개로 잇는다.
    """
    tol = cfg.snap_tol
    table_bottom = table_bbox[3]
    limit = float("inf") if next_table_top is None else next_table_top - tol
    below = [ch for ch in chars if table_bottom + tol < (ch.top + ch.bottom) / 2 < limit]
    lines: list[tuple[float, float, str]] = []  # (top, bottom, text)
    for line in _group_lines(below):
        text = "".join(ch.text for ch in line).strip()
        if text:  # 공백뿐인 줄은 건너뛴다
            lines.append((min(ch.top for ch in line), max(ch.bottom for ch in line), text))
    prefixes = tuple(unicodedata.normalize("NFKC", p) for p in cfg.note_prefixes)

    def is_note_start(text: str) -> bool:
        return unicodedata.normalize("NFKC", text).startswith(prefixes)

    if not lines or not is_note_start(lines[0][2]):
        return []
    if lines[0][0] - table_bottom > cfg.note_max_gap + _EPS:
        return []

    result = [(lines[0][0], lines[0][1], lines[0][2], True)]
    prev_bottom = lines[0][1]
    for top, bottom, text in lines[1:]:
        if top - prev_bottom > cfg.note_max_gap + _EPS:
            break
        result.append((top, bottom, text, is_note_start(text)))
        prev_bottom = bottom
    return result


# --------------------------------------------------------------------------
# 표 하나의 전체 파싱
# --------------------------------------------------------------------------

@dataclass
class ParsedTable:
    """표 하나의 파싱 결과.

    page: 1-based. bbox: [x0, top, x1, bottom] (region 기준).
    header_rows: header 줄 수 (경계선을 못 찾으면 0). columns: 열 이름 (병합된 header는 header_join으로 이음).
    notes: 표 아래 (주) 주석 항목. warnings: 경고 코드 문자열 (NO_HEADER_BOUNDARY,
    DUP_COLUMN_NAME, EMPTY_COLUMN_NAME).
    notes_bottom: 마지막 주석 줄의 bottom (주석이 없으면 None). 본문 파싱이 주석 글자를 뺄 때 쓴다.
    """

    parser_version: str
    page: int
    bbox: list[float]
    grid: Grid
    header_rows: int
    columns: list[str]
    cells: list[Cell]
    records: list[RowRecord]
    html: str
    notes: list[str]
    grid_check: GridCheck
    char_check: CharCheck
    warnings: list[str] = field(default_factory=list)
    notes_bottom: float | None = None


def parse_table(
    geom: PageGeometry, region: TableRegion, cfg: TableConfig, next_table_top: float | None = None
) -> ParsedTable:
    """region 하나를 격자 복원부터 자체 검사, 주석 연결까지 파싱한다.

    next_table_top은 같은 페이지에서 이 표 아래에 있는 다음 표의 top (주석 범위의 끝).
    """
    grid = build_grid(geom.segments, region, cfg)
    flags = build_edge_flags(grid, geom.segments, region, cfg)
    cells = assign_chars(build_cells(grid, flags), grid, geom.chars, region, cfg)
    header_rows = find_header_end(grid, flags)
    cells = mark_header(cells, header_rows)
    columns = build_columns(cells, grid, header_rows, cfg)
    records = build_records(cells, grid, header_rows)
    table_html = to_html(cells, header_rows)
    grid_check = check_grid(grid, cells, flags)
    char_check = check_chars(cells, geom.chars, region, grid, cfg)
    note_lines = _note_lines(region.bbox, geom.chars, next_table_top, cfg)
    notes = _join_notes(note_lines, cfg.note_prefixes)

    warnings: list[str] = []
    if header_rows == 0:
        warnings.append("NO_HEADER_BOUNDARY")
    named = [name for name in columns if name]
    if len(set(named)) != len(named):
        warnings.append("DUP_COLUMN_NAME")
    if len(named) != len(columns):
        warnings.append("EMPTY_COLUMN_NAME")

    return ParsedTable(
        parser_version=PARSER_VERSION,
        page=region.page,
        bbox=list(region.bbox),
        grid=grid,
        header_rows=header_rows,
        columns=columns,
        cells=cells,
        records=records,
        html=table_html,
        notes=notes,
        grid_check=grid_check,
        char_check=char_check,
        warnings=warnings,
        notes_bottom=note_lines[-1][1] if note_lines else None,
    )


def split_regions(geom: PageGeometry, cfg: TableConfig) -> tuple[list[TableRegion], list[TableRegion]]:
    """페이지의 선 묶음을 (표, 상자)로 나눈다.

    격자가 1행 x 1열인 영역은 표가 아니라 테두리 상자 (표지 제목 상자 등)다. 상자 안 글자는 본문 글자로 남는다.
    행이나 열이 2개 이상이면 표다.
    """
    tables: list[TableRegion] = []
    boxes: list[TableRegion] = []
    for region in find_table_regions(geom.segments, cfg, geom.page):
        grid = build_grid(geom.segments, region, cfg)
        (boxes if grid.n_rows == 1 and grid.n_cols == 1 else tables).append(region)
    return tables, boxes


def parse_pdf_tables(
    pdf_path: str, cfg: TableConfig, pages: list[int] | None = None
) -> tuple[list[ParsedTable], list[PageGeometry]]:
    """PDF의 지정한 페이지 (None이면 전체, 1-based)에서 표를 모두 파싱한다.

    반환: (표 목록, 페이지 geometry 목록). 표는 페이지 순, 페이지 안에서는 위에서 아래 순.
    1행 x 1열 상자는 표 목록에 넣지 않는다 (split_regions).
    geometry는 리포트용으로 같이 돌려준다 (pages 순서대로, 표가 없는 페이지도 포함).
    각 표의 next_table_top은 같은 페이지에서 그 표 bottom 아래에 있는 표 중 가장 위의 top이다.
    """
    page_nos = list(range(1, count_pages(pdf_path) + 1)) if pages is None else list(pages)
    tables: list[ParsedTable] = []
    geoms: list[PageGeometry] = []
    for page_no in page_nos:
        geom = load_page_geometry(pdf_path, page_no, cfg)
        geoms.append(geom)
        regions, _boxes = split_regions(geom, cfg)
        for region in regions:
            below = [r.bbox[1] for r in regions if r.bbox[1] >= region.bbox[3] - cfg.snap_tol]
            tables.append(parse_table(geom, region, cfg, min(below) if below else None))
    return tables, geoms


# --------------------------------------------------------------------------
# 정답 대조 (원문 없는 결과)
# --------------------------------------------------------------------------

_EXPECTED_TABLE_KEYS = frozenset(
    {"page", "index", "header_rows", "n_rows", "n_cols", "cells", "n_notes"}
)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_expected(expected: Any) -> list[dict[str, Any]]:
    """expected의 형식을 검사해 표 항목 목록을 돌려준다. 오류 메시지에는 값을 넣지 않는다."""
    if not isinstance(expected, dict) or not isinstance(expected.get("tables"), list):
        raise ValueError("expected 형식 오류: 최상위에 tables 목록이 필요하다")
    entries = expected["tables"]
    for e in entries:
        if not isinstance(e, dict) or not _is_int(e.get("page")):
            raise ValueError("expected 형식 오류: 표 항목은 정수 page를 가진 객체여야 한다")
        for key in ("index", "header_rows", "n_rows", "n_cols", "n_notes"):
            if key in e and not _is_int(e[key]):
                raise ValueError("expected 형식 오류: 정수 항목에 정수가 아닌 값이 있다")
        if "cells" in e and not (
            isinstance(e["cells"], list)
            and all(
                isinstance(c, dict) and all(_is_int(c.get(k)) for k in ("row", "col", "rowspan", "colspan"))
                for c in e["cells"]
            )
        ):
            raise ValueError("expected 형식 오류: cells 항목은 row, col, rowspan, colspan 정수가 필요하다")
    return entries


def _compare_table(table: ParsedTable, e: dict[str, Any], page: int, index: int) -> dict[str, Any]:
    """표 하나와 정답 항목 하나의 대조. 결과에는 bool, 개수, 위치만 넣는다."""
    unknown = len(set(e) - _EXPECTED_TABLE_KEYS)
    res: dict[str, Any] = {
        "page": page,
        "index": index,
        "found": True,
        "unknown_keys": unknown,
        "header_rows_ok": None,
        "n_rows_ok": None,
        "n_cols_ok": None,
        "cells": None,
        "n_notes_ok": None,
    }
    if "header_rows" in e:
        res["header_rows_ok"] = table.header_rows == e["header_rows"]
    if "n_rows" in e:
        res["n_rows_ok"] = table.grid.n_rows == e["n_rows"]
    if "n_cols" in e:
        res["n_cols_ok"] = table.grid.n_cols == e["n_cols"]
    if "n_notes" in e:
        res["n_notes_ok"] = len(table.notes) == e["n_notes"]

    if "cells" in e:
        actual = {(c.row, c.col): c for c in table.cells}
        exp_pos = {(c["row"], c["col"]) for c in e["cells"]}
        span_bad: set[tuple[int, int]] = set()
        text_bad: set[tuple[int, int]] = set()
        header_bad: set[tuple[int, int]] = set()
        for ec in e["cells"]:
            pos = (ec["row"], ec["col"])
            cell = actual.get(pos)
            if cell is None:
                continue
            if (cell.rowspan, cell.colspan) != (ec["rowspan"], ec["colspan"]):
                span_bad.add(pos)
            if "text" in ec and cell.text != ec["text"]:
                text_bad.add(pos)
            if "is_header" in ec and cell.is_header != bool(ec["is_header"]):
                header_bad.add(pos)
        res["cells"] = {
            "missing": [list(p) for p in sorted(exp_pos - set(actual))],
            "extra": [list(p) for p in sorted(set(actual) - exp_pos)],
            "span_mismatch": [list(p) for p in sorted(span_bad)],
            "text_mismatch": [list(p) for p in sorted(text_bad)],
            "is_header_mismatch": [list(p) for p in sorted(header_bad)],
        }

    checks: list[bool] = [unknown == 0]
    checks += [res[k] for k in ("header_rows_ok", "n_rows_ok", "n_cols_ok", "n_notes_ok") if res[k] is not None]
    if res["cells"] is not None:
        checks.append(not any(res["cells"].values()))
    res["ok"] = all(checks)
    return res


def compare_to_expected(tables: list[ParsedTable], expected: dict[str, Any]) -> dict[str, Any]:
    """파싱 결과를 정답과 대조한다. 결과에 문자열 값은 넣지 않는다 (bool, 개수, 위치만).

    expected: {"tables": [{"page": int, "index": int (페이지 안 순서, 기본 0),
      "header_rows": int?, "n_rows": int?, "n_cols": int?, "n_notes": int?,
      "cells": [{"row", "col", "rowspan", "colspan", "text"?, "is_header"?}]?}]}
    선택 항목(?)은 있을 때만 대조한다. 표 항목에 모르는 키가 있으면 unknown_keys로 세고 불일치로 본다.
    열 이름과 행 레코드는 셀 구조와 셀 글자에서 결정되므로 따로 대조하지 않는다.
    형식이 틀리면 ValueError (메시지에 값 없음).

    반환: {"ok", "n_expected", "n_found", "tables": [표별 결과], "unlisted_tables": [[page, index]]}.
    표별 결과는 found (못 찾으면 found=False, ok=False)와 항목별 결과다: 정답에 없는 항목은 None,
    있는 항목은 bool 또는 위치 목록 ([row, col]).
    expected에 없는 표(unlisted_tables)는 알려주기만 하고 ok에는 영향이 없다.
    """
    entries = _validate_expected(expected)
    by_page: dict[int, list[ParsedTable]] = {}
    for table in tables:
        by_page.setdefault(table.page, []).append(table)

    results: list[dict[str, Any]] = []
    matched: set[tuple[int, int]] = set()
    for e in entries:
        page = e["page"]
        index = e.get("index", 0)
        page_tables = by_page.get(page, [])
        if not 0 <= index < len(page_tables):
            results.append({"page": page, "index": index, "found": False, "ok": False})
            continue
        matched.add((page, index))
        results.append(_compare_table(page_tables[index], e, page, index))

    unlisted = [
        [page, i] for page in sorted(by_page) for i in range(len(by_page[page])) if (page, i) not in matched
    ]
    return {
        "ok": all(r["ok"] for r in results),
        "n_expected": len(entries),
        "n_found": sum(1 for r in results if r["found"]),
        "tables": results,
        "unlisted_tables": unlisted,
    }
