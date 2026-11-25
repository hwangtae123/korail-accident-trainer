"""backlog BE-1 ~ BE-4 수용 기준 테스트 (API 키 없이, 가짜 LLM·stub 임베딩).
가상 보고서는 tests/test_flow.py의 make_pdf로 만든다 (테스트용, 실제 사고 아님).
"""
import json
import tempfile
from pathlib import Path

import pytest

from tests.test_flow import fake_llm, make_pdf  # noqa: F401  (환경변수 DATA_DIR/LLM/EMBED 설정 포함)

from app import search, store
from app.schema import AccidentRecord, Evidence, Item
from app.verify import check, page_texts, verify_evidence


@pytest.fixture(autouse=True)
def own_data_dir(tmp_path, monkeypatch):
    """테스트마다 빈 저장소를 쓴다 (test_flow의 보고서 수 검사와 섞이지 않게)."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "data")
    search.reset_client()
    yield
    search.reset_client()


# ---------- BE-1 근거 자동 확인 ----------

PAGES = ["[p.1]\n표지", "[p.2]\n기관사는 신호를\n확인하지 않고 출발하였다.", "[p.3]\n안전권고 문장"]


def test_verify_true_false_null():
    pages = page_texts(PAGES)
    assert check(Evidence(page=2, quote="신호를 확인하지 않고"), pages) is True  # 줄바꿈 차이 무시
    assert check(Evidence(page=2, quote="신호를확인하지 않고 출발"), pages) is True  # 띄어쓰기 차이 무시
    assert check(Evidence(page=2, quote="기관사는 … 출발하였다"), pages) is True  # 줄임표로 생략
    assert check(Evidence(page=3, quote="신호를 확인하지 않고"), pages) is False  # 다른 쪽
    assert check(Evidence(page=2, quote="없는 구절"), pages) is False
    assert check(Evidence(page=9, quote="표지"), pages) is False  # 없는 쪽
    assert check(Evidence(page=2, quote=""), pages) is None
    assert check(Evidence(page=None, quote="표지"), pages) is None


def test_verify_overrides_llm_value():
    rec = AccidentRecord(
        title="테스트용 가상 보고서", summary="테스트",
        direct_causes=[Item(text="a", evidence=Evidence(page=2, quote="없는 구절", verified=True)),
                       Item(text="b", evidence=Evidence(page=2, quote="출발하였다", verified=False)),
                       Item(text="c", evidence=Evidence(page=None, quote="", verified=True))],
    )
    verify_evidence(rec, PAGES)
    assert [c.evidence.verified for c in rec.direct_causes] == [False, True, None]


def _client(stub):
    from fastapi.testclient import TestClient

    from app import llm
    from app.main import app

    llm.set_stub(stub)
    return TestClient(app)


def _upload(client, tag: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / f"{tag}.pdf"
        make_pdf(pdf, tag)
        res = client.post("/api/reports", files={"file": (f"{tag}.pdf", pdf.read_bytes(), "application/pdf")})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_pipeline_fills_verified():
    def stub(system, user):
        out = fake_llm(system, user)
        if "구조화하는 분석가" in system:
            rec = json.loads(out)
            rec["direct_causes"] = [
                {"text": "맞는 구절", "evidence": {"page": 4, "quote": "교육이 이론 위주로", "verified": False}},
                {"text": "지어낸 구절", "evidence": {"page": 4, "quote": "존재하지 않는 문장", "verified": True}},
                {"text": "빈 구절", "evidence": {"page": 4, "quote": ""}},
            ]
            return json.dumps(rec, ensure_ascii=False)
        return out

    client = _client(stub)
    rid = _upload(client, "V")
    rec = client.get(f"/api/reports/{rid}").json()["record"]
    assert [c["evidence"]["verified"] for c in rec["direct_causes"]] == [True, False, None]
    # 시나리오 근거도 확인된다 (fake_llm: p.4 "테스트")
    assert client.get(f"/api/reports/{rid}/scenario").json()["steps"][0]["evidence"]["verified"] is True


# ---------- BE-2 시나리오 저장 API ----------

def test_put_scenario():
    client = _client(fake_llm)
    rid = _upload(client, "S")
    assert client.post(f"/api/reports/{rid}/scenario/review").json()["ok"]
    sc = client.get(f"/api/reports/{rid}/scenario").json()
    assert sc["review_status"] == "검수 완료"

    sc["intro"] = "교관이 고친 도입 (테스트)"
    sc["steps"][0]["options"].append({"id": "C", "text": "새 선택지"})
    sc["steps"][0]["answer_id"] = "C"
    res = client.put(f"/api/reports/{rid}/scenario", json=sc)
    assert res.status_code == 200, res.text
    assert res.json()["review_status"] == "검수 전"  # 고치면 다시 검수 전

    got = client.get(f"/api/reports/{rid}/scenario").json()
    assert got["intro"] == "교관이 고친 도입 (테스트)" and got["steps"][0]["answer_id"] == "C"
    assert got["review_status"] == "검수 전"

    bad = json.loads(json.dumps(sc))
    bad["steps"][0]["answer_id"] = "Z"
    res = client.put(f"/api/reports/{rid}/scenario", json=bad)
    assert res.status_code == 422 and "Z" in res.json()["detail"]
    assert client.get(f"/api/reports/{rid}/scenario").json()["steps"][0]["answer_id"] == "C"  # 저장 안 됨

    assert client.put("/api/reports/nope000000/scenario", json=sc).status_code == 404
