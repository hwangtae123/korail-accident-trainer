"""보고서 그림·사진 뽑기: "[그림N] 제목" 설명 줄을 기준으로 그 위(또는 아래) 그림 영역을 잘라 이미지로 만든다.

- 설명 줄: "[그림3] 사고 열차 연결 및 탈선된 트롤리" 처럼 줄 맨 앞이 [그림N]/[사진N]이고 짧은 줄.
  본문에서 그림을 가리키는 문장("[그림2]와 같이 …")은 뺀다.
- 그림 영역: 설명 줄 바로 위의 본문 줄(긴 문장) 아래부터 설명 줄 위까지. 사진(래스터)과 도면(벡터)을 모두 담는다.
  위에 공간이 없으면 설명 줄 아래쪽을 본다. 같은 높이에 설명 줄이 둘 이상이면(나란히 놓인 그림) 가로로 나눈다.
- 150dpi로 그려서 잘라 WebP로 줄인다 (긴 변 최대 1400px).
글자를 읽을 수 없는 PDF(OCR 대상)는 설명 줄을 찾지 못하므로 그림도 없다.
"""
import io
import re
from dataclasses import dataclass
from pathlib import Path

CAPTION = re.compile(r"^\s*[\[［]\s*(그림|사진)\s*(\d+(?:\s*-\s*\d+)?)\s*[\]］]\s*(.*)$")
# "[그림2]와 같이", "[그림3]에서 보는 바와 같이" … 본문 문장
REFERENCE = re.compile(r"^(와|과|은|는|에|을|를|의|처럼|참조|에서|및|,|\.|이|가|로|으로)")
X_TOL = 1.5
DPI = 150
MAX_SIDE = 1400
MIN_H, MIN_W = 40, 60  # pt
MAX_FIGS = 80


@dataclass
class Figure:
    n: int
    page: int
    label: str      # "그림 3"
    caption: str    # "사고 열차 연결 및 탈선된 트롤리"
    width: int
    height: int
    data: bytes     # WebP

    def meta(self) -> dict:
        return {"n": self.n, "page": self.page, "label": self.label, "caption": self.caption,
                "width": self.width, "height": self.height}


def _captions(lines: list[dict]) -> list[dict]:
    out = []
    for ln in lines:
        m = CAPTION.match(ln["text"])
        if not m:
            continue
        rest = m.group(3).strip()
        if REFERENCE.match(rest) or len(ln["text"]) > 60:
            continue
        out.append({**ln, "label": f"{m.group(1)} {m.group(2).replace(' ', '')}", "caption": rest})
    return out


def _graphics(page) -> list[tuple[float, float, float, float]]:
    """쪽의 그래픽 요소 범위: 사진(래스터), 도형, 선. 짧은 선(밑줄·각주 구분선 조각)은 뺀다."""
    pw, ph = float(page.width), float(page.height)
    out = []
    for im in page.images:
        out.append((im["x0"], im["top"], im["x1"], im["bottom"]))
    for o in list(page.rects) + list(page.curves) + list(page.lines):
        w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
        if max(w, h) < 20:
            continue
        if h < 3 and w > pw * 0.6 and (o["top"] < 95 or o["top"] > ph - 70):
            continue  # 쪽 머리글·바닥글 가로줄
        out.append((o["x0"], o["top"], o["x1"], o["bottom"]))
    return out


TABLE_CAPTION = re.compile(r"^\s*[\[［]\s*표\s*\d+")


def _boundaries(lines: list[dict]) -> list[tuple[float, float]]:
    """그림 영역을 끊는 곳: 문단(긴 줄이 2줄 이상 붙어 있음)과 다른 설명 줄(그림·사진·표). (top, bottom) 목록.
    한 줄짜리 긴 줄은 그림 안의 이름표("② 운전실 뒤 영상으로 본 …")일 수 있어 경계로 보지 않는다."""
    ls = sorted(lines, key=lambda ln: ln["top"])
    long_ = [ln for ln in ls if len(ln["text"].strip()) >= 30 and not CAPTION.match(ln["text"])
             and not TABLE_CAPTION.match(ln["text"])]
    out, run = [], []
    for ln in long_:
        if run and ln["top"] - run[-1]["bottom"] > 12:
            if len(run) >= 2:
                out.append((run[0]["top"], run[-1]["bottom"]))
            run = []
        run.append(ln)
    if len(run) >= 2:
        out.append((run[0]["top"], run[-1]["bottom"]))
    out += [(ln["top"], ln["bottom"]) for ln in ls if CAPTION.match(ln["text"]) or TABLE_CAPTION.match(ln["text"])]
    return out


def _fit(box, graphics, lines) -> tuple[float, float, float, float] | None:
    """영역을 그 안의 그래픽 범위로 좁힌다 (+ 그 사이·바로 위의 글자: 도면 이름표, 사진 설명). 그래픽이 없거나 작으면 None."""
    x0, top, x1, bottom = box
    inside = [g for g in graphics if x0 - 2 <= (g[0] + g[2]) / 2 <= x1 + 2 and top - 2 <= (g[1] + g[3]) / 2 <= bottom + 2]
    if not inside:
        return None
    gt, gb = min(g[1] for g in inside), max(g[3] for g in inside)
    if gb - gt < MIN_H * 0.6:  # 선 한두 개뿐 (각주 구분선 등)
        return None
    labels = [ln for ln in lines if not CAPTION.match(ln["text"]) and ln["top"] >= max(top, gt - 15) - 1
              and ln["bottom"] <= bottom + 1 and x0 - 2 <= ln["x0"] and ln["x1"] <= x1 + 2]
    t = min([gt] + [ln["top"] for ln in labels]) - 4
    b = max([gb] + [ln["bottom"] for ln in labels]) + 4
    return (x0, max(top, t), x1, min(bottom, b))


def _regions(page, lines: list[dict], caps: list[dict]) -> list[tuple[dict, tuple[float, float, float, float]]]:
    pw, ph = float(page.width), float(page.height)
    left = min((ln["x0"] for ln in lines), default=40.0)
    right = max((ln["x1"] for ln in lines), default=pw - 40)
    head = min(70.0, min((ln["bottom"] for ln in lines), default=60.0))  # 쪽 머리글 아래
    graphics = _graphics(page)
    bounds = _boundaries(lines)
    out = []
    for c in caps:
        # 같은 높이의 설명 줄들 (나란히 놓인 그림) -> 가로 범위를 나눈다
        row = sorted([o for o in caps if abs(o["top"] - c["top"]) < 8], key=lambda o: o["x0"])
        k = row.index(c)
        mids = [(row[i]["x1"] + row[i + 1]["x0"]) / 2 for i in range(len(row) - 1)]
        x0 = left - 4 if k == 0 else mids[k - 1]
        x1 = right + 4 if k == len(row) - 1 else mids[k]
        # 위쪽: 설명 줄 위에서 가장 가까운 경계(문단·다른 설명 줄)의 아래
        top = max([b for t, b in bounds if b <= c["top"] - 2], default=head) + 2
        box = _fit((x0, top, x1, c["top"] - 1), graphics, lines)
        if box is None or box[3] - box[1] < MIN_H:  # 위에 그림이 없으면 설명 줄 아래쪽
            bottom = min([t for t, b in bounds if t >= c["bottom"] + 2], default=ph - 50) - 2
            box = _fit((x0, c["bottom"] + 1, x1, bottom), graphics, lines)
        if box and box[3] - box[1] >= MIN_H and box[2] - box[0] >= MIN_W:
            out.append((c, box))
    return out


def extract(pdf_path: str | Path) -> list[Figure]:
    import pdfplumber
    import pypdfium2 as pdfium
    from PIL import Image

    figs: list[Figure] = []
    seen_labels: set[str] = set()
    pdoc = pdfium.PdfDocument(str(pdf_path))
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                lines = page.extract_text_lines(x_tolerance=X_TOL)
                caps = [c for c in _captions(lines) if c["label"] not in seen_labels]
                if not caps:
                    continue
                regions = _regions(page, lines, caps)
                if not regions:
                    continue
                scale = DPI / 72
                img = pdoc[pno - 1].render(scale=scale).to_pil().convert("RGB")
                for c, (x0, top, x1, bottom) in regions:
                    crop = img.crop((max(0, int(x0 * scale)), max(0, int(top * scale)),
                                     min(img.width, int(x1 * scale)), min(img.height, int(bottom * scale))))
                    if crop.getbbox() is None or _blank(crop):
                        continue
                    crop.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                    buf = io.BytesIO()
                    crop.save(buf, "WEBP", quality=80, method=4)
                    seen_labels.add(c["label"])
                    figs.append(Figure(n=len(figs) + 1, page=pno, label=c["label"], caption=c["caption"],
                                       width=crop.width, height=crop.height, data=buf.getvalue()))
                    if len(figs) >= MAX_FIGS:
                        return figs
    finally:
        pdoc.close()
    return figs


def extract_and_save(rid: str, pdf_path: str | Path) -> list[dict]:
    """뽑아서 저장한다: 이미지는 store.save_blob(figures/<n>.webp), 목록은 store 문서 'figures'. 목록을 돌려준다."""
    import hashlib
    from concurrent.futures import ThreadPoolExecutor

    from . import store

    figs = extract(pdf_path)
    metas = []
    for f in figs:
        m = f.meta()
        m["key"] = hashlib.sha1(f.data).hexdigest()[:8]  # 바뀌면 화면의 캐시도 새로 받도록
        metas.append(m)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda f: store.save_blob(rid, f"figures/{f.n}.webp", f.data, "image/webp"), figs))
    store.write(rid, "figures", metas)
    return metas


def _blank(img) -> bool:
    """거의 흰 영역(잘못 잡힌 여백)은 버린다."""
    g = img.convert("L").resize((64, 64))
    dark = sum(g.histogram()[:235])
    return dark < 64 * 64 * 0.01
