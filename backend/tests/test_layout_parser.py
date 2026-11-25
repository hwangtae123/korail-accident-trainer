"""레이아웃 파서 연동 (app/layout_parser.py) 테스트."""
from tests.test_be import _client, _upload, own_data_dir  # noqa: F401  (autouse fixture: 테스트마다 빈 저장소)
from tests.test_flow import fake_llm


# ---------- 레이아웃 파서가 실패하면 다른 방식으로 넘어가지 않고 error + 이유 ----------

def test_layout_parser_failure_is_error(monkeypatch, tmp_path):
    from app import layout_parser

    monkeypatch.setattr(layout_parser, "PARSER_DIR", tmp_path / "no-parser")
    client = _client(fake_llm)
    rid = _upload(client, "F")
    st = client.get(f"/api/reports/{rid}").json()["status"]
    assert st["state"] == "error" and "레이아웃 파서가 없습니다" in st["message"], st


def test_pdf_without_readable_hangul_needs_ocr(tmp_path):
    """숫자·기호만 읽히고 한글은 못 읽는 PDF는 파서·LLM을 돌리지 않고 OCR 필요로 멈춘다."""
    import pytest
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    from app.parse import NeedsOCR, parse_report

    pdf = tmp_path / "digits.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    for _ in range(3):
        for i in range(30):
            c.drawString(60, 800 - i * 22, f"2024 8 18 ( ) 16 32 39 KTX ( 14:28 -> 17:14 ) {i} 306.943 km")
        c.showPage()
    c.save()
    with pytest.raises(NeedsOCR, match="한글을 읽을 수 없는"):
        parse_report(pdf)
