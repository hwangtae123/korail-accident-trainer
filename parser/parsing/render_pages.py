"""쪽 그림: PDF 쪽을 PNG로 렌더한다 → secure/renders/pNNN.png (원문 이미지라 secure에만).

pypdfium2 (pdfplumber와 같이 설치됨) 배율 2.0 = 144 DPI. 예시 그림 자르기 (tree.py)와 사람 확인용 그림이 쓴다.
이미 있는 쪽은 건너뛴다 (다시 만들려면 --force).
실행 (requirements.txt 환경): python parsing/render_pages.py [--force]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import doc, doc_pdf  # noqa: E402
from safeio import SECURE, out, secure_path, setup  # noqa: E402

DPI = 144
SCALE = DPI / 72


def main() -> int:
    setup("render_pages")
    import pypdfium2 as pdfium

    force = "--force" in sys.argv
    render_dir = SECURE / "renders"
    pdf = pdfium.PdfDocument(str(doc_pdf()))
    n_done = 0
    for i in range(len(pdf)):
        path = render_dir / f"p{i + 1:03d}.png"
        if path.exists() and not force:
            continue
        pdf[i].render(scale=SCALE).to_pil().convert("RGB").save(secure_path(path))
        n_done += 1
    out("done", pages=len(pdf), expected=doc()["pages"], rendered=n_done, dpi=DPI)
    pdf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
