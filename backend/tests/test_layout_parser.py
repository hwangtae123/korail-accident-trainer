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
