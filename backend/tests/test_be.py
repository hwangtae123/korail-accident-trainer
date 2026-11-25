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


# ---------- BE-3 작업 전 브리핑 API ----------

def _briefing_stub(seen_user: list):
    def stub(system, user):
        if "안전 브리핑(TBM)" in system:
            seen_user.append(user)
            rid = __import__("re").search(r"R1: .*?\(id: (\w+)", user).group(1)
            return json.dumps({
                "summary": "테스트 요약 [테스트용 가상 보고서 p.4]",
                "checklist": [
                    {"text": "테스트 권고를 확인했는가?", "source_item": "R1-1", "source_report_id": rid},
                    {"text": "출처 번호가 없는 항목", "source_item": "R9-9", "source_report_id": rid},
                    {"text": "검색 안 된 보고서", "source_item": "R1-1", "source_report_id": "not-searched"},
                ],
            }, ensure_ascii=False)
        out = fake_llm(system, user)
        if "구조화하는 분석가" in system:
            rec = json.loads(out)
            rec["recommendations"] = [{"target": "한국철도공사", "text": "테스트 권고를 이행할 것",
                                       "evidence": {"page": 5, "quote": "테스트 권고"}}]
            rec["contributing_factors"] = [{"text": "테스트 기여요인", "evidence": {"page": 4, "quote": "기여요인"}}]
            return json.dumps(rec, ensure_ascii=False)
        return out
    return stub


def test_briefing_empty_when_no_reports():
    client = _client(fake_llm)
    res = client.post("/api/briefing", json={"work": "야간 선로 작업"})
    assert res.status_code == 200, res.text
    assert res.json() == {"work": "야간 선로 작업", "summary": "", "checklist": [], "similar": []}


def test_briefing_checklist_sources():
    seen = []
    client = _client(_briefing_stub(seen))
    ids = {_upload(client, "A"), _upload(client, "B")}
    res = client.post("/api/briefing", json={"work": "테스트 직접 원인 작업"})
    assert res.status_code == 200, res.text
    b = res.json()
    assert b["summary"].startswith("테스트 요약")
    assert {g["report_id"] for g in b["similar"]} == ids
    # 출처를 확인할 수 없는 두 항목은 버리고, 남은 항목은 원래 권고의 evidence를 그대로 쓴다
    assert len(b["checklist"]) == 1
    item = b["checklist"][0]
    assert item["source_report_id"] in ids and item["source_title"].startswith("테스트용 가상 보고서")
    assert item["evidence"]["page"] == 5 and item["evidence"]["quote"] == "테스트 권고"
    # LLM에는 안전권고·기여요인만 들어간다 (본문 조각이나 경위는 넣지 않음)
    assert "테스트 권고를 이행할 것" in seen[0] and "테스트 기여요인" in seen[0]
    assert "테스트 경위" not in seen[0]
    assert client.post("/api/briefing", json={"work": ""}).status_code == 422


# ---------- BE-4 규정 이름 맞추기 ----------

def test_rule_name_variants_are_same():
    from app.rule_aliases import canonical_key

    same = ["선로유지관리지침", "선로 유지관리 지침", "「선로유지관리지침」", "한국철도공사 선로유지관리지침",
            "선로유지관리지침 제12조", "(한국철도공사) 선로유지관리지침 제12조제1항"]
    assert len({canonical_key(x) for x in same}) == 1, {x: canonical_key(x) for x in same}
    assert canonical_key("철도안전법 제40조의2") == canonical_key("철도안전법")
    assert canonical_key("차량운전규칙") == canonical_key("철도차량운전규칙")
    assert canonical_key("철도안전법") != canonical_key("철도안전법 시행규칙")
    assert canonical_key("운전취급규정") != canonical_key("선로유지관리지침")


def test_shared_rules_with_different_spelling():
    names = {"A": "선로유지관리지침", "B": "한국철도공사 선로 유지관리 지침 제12조"}

    def stub(system, user):
        out = fake_llm(system, user)
        if "구조화하는 분석가" in system:
            rec = json.loads(out)
            tag = rec["title"][-1]
            rec["violated_rules"] = [{"rule_name": names[tag], "description": "테스트",
                                      "evidence": {"page": 4, "quote": "테스트"}}]
            return json.dumps(rec, ensure_ascii=False)
        return out

    client = _client(stub)
    a = _upload(client, "A")
    b = _upload(client, "B")
    rel = client.get(f"/api/reports/{b}/related").json()
    assert [g["report_id"] for g in rel] == [a]
    assert rel[0]["shared_rules"] == [names["B"]]  # 이번 보고서의 표기로 보여준다
    stats = client.get("/api/stats").json()
    assert len(stats["violated_rules"]) == 1 and stats["violated_rules"][0]["count"] == 2


# ---------- LLM 실패는 502 + 이유 ----------

def test_llm_failure_returns_502_with_reason(monkeypatch):
    from app import llm

    client = _client(fake_llm)
    _upload(client, "A")
    llm.set_stub(None)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    try:
        res = client.post("/api/ask", json={"q": "테스트 직접 원인"})
    finally:
        llm.set_stub(fake_llm)
    assert res.status_code == 502
    assert "LLM 호출 실패" in res.json()["detail"] and "LLM_MODEL" in res.json()["detail"]


# ---------- simple 벡터 저장소: 다른 프로세스가 쓴 내용을 다시 읽는다 ----------

def test_simple_store_sees_other_writer(tmp_path):
    from app.vectorstore import SimpleCollection

    server = SimpleCollection(tmp_path / "v")  # 서버 프로세스가 들고 있는 것
    ingest = SimpleCollection(tmp_path / "v")  # scripts/ingest.py가 따로 연 것
    server.add(["a:0"], ["가"], [[1.0, 0.0]], [{"report_id": "a"}])
    ingest.add(["b:0"], ["나"], [[0.0, 1.0]], [{"report_id": "b"}])
    assert ingest.count() == 2  # 서버가 쓴 a를 지우지 않았다
    assert server.count() == 2  # 서버도 ingest가 쓴 b를 본다
    server.add(["c:0"], ["다"], [[1.0, 1.0]], [{"report_id": "c"}])
    assert {m["report_id"] for m in SimpleCollection(tmp_path / "v").metadatas} == {"a", "b", "c"}


# ---------- 검색 조각에서 표 줄은 뺀다 ----------

def test_page_chunks_skip_tables():
    sec = "[p.3]\n본문 문장 하나\n\n[표 p.3-1] 교육 실적\n| 구분 | 이론 |\n|---|---|\n| 시간 | 16 |\n[p.4]\n본문 문장 둘"
    chunks = search._page_chunks(sec)
    text = "\n".join(t for t, _ in chunks)
    assert "본문 문장 하나" in text and "본문 문장 둘" in text
    assert "|" not in text and "[표" not in text
    assert chunks[0][1] == 3


# ---------- 파일 저장소: 읽는 중에 써도 Windows에서 PermissionError가 나지 않는다 ----------

def test_file_store_concurrent_read_write():
    import threading

    rid = "concurrent"
    store.write(rid, "status", {"state": "queued", "n": 0})
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                assert store.read(rid, "status")["state"] == "queued"
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    ts = [threading.Thread(target=reader) for _ in range(3)]
    for t in ts:
        t.start()
    try:
        for i in range(300):
            store.write(rid, "status", {"state": "queued", "n": i})
    finally:
        stop.set()
        for t in ts:
            t.join()
    assert not errors, errors[:3]
    assert store.read(rid, "status")["n"] == 299


# ---------- 화면을 Vercel에 따로 배포할 때: CORS ----------

def test_cors_allows_vercel_origins():
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "from fastapi.testclient import TestClient\n"
        "from app.main import app\n"
        "c = TestClient(app)\n"
        "def pre(o):\n"
        "    r = c.options('/api/reports', headers={'Origin': o, 'Access-Control-Request-Method': 'POST'})\n"
        "    return r.headers.get('access-control-allow-origin')\n"
        "print(pre('https://accident-trainer.vercel.app'), pre('https://accident-trainer-git-main-team.vercel.app'),"
        " pre('https://evil.example.com'), pre('https://kr.example.org'))\n"
    )
    env = {**__import__("os").environ, "CORS_ORIGINS": "https://kr.example.org/",
           "CORS_ORIGIN_REGEX": r"https://accident-trainer(-[a-z0-9-]+)?\.vercel\.app"}
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, env=env,
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    allowed = out.stdout.split()[-4:]
    assert allowed == ["https://accident-trainer.vercel.app", "https://accident-trainer-git-main-team.vercel.app",
                       "None", "https://kr.example.org"], out.stdout


# ---------- 서버리스(Vercel) 처리 방식 ----------

def test_config_and_upload_url_in_file_mode():
    client = _client(fake_llm)
    assert client.get("/api/config").json()["direct_upload"] is False
    r = client.post("/api/reports/upload-url", json={"id": "0123456789", "filename": "a.pdf"})
    assert r.status_code == 400
    assert client.post("/api/reports/upload-url", json={"id": "not-hex!!", "filename": "a.pdf"}).status_code == 422


def test_in_request_processing_and_stale_heal(monkeypatch):
    from datetime import datetime, timedelta

    from app import pipeline

    monkeypatch.setenv("PROCESS_IN_REQUEST", "1")
    client = _client(fake_llm)
    rid = _upload(client, "R")  # 요청 안에서 끝까지 처리된다
    assert client.get(f"/api/reports/{rid}").json()["status"]["state"] == "done"

    # 함수가 시간 제한에 걸려 '처리 중'으로 멈춘 상황
    old = (datetime.now() - timedelta(seconds=pipeline.STALE_SEC + 5)).isoformat()
    st = store.read(rid, "status")
    store.write(rid, "status", {**st, "state": "extracting", "updated_at": old})
    got = client.get(f"/api/reports/{rid}").json()["status"]
    assert got["state"] == "error" and "시간이 초과" in got["message"]
    # 업로드 도중 멈춘 상황
    store.write(rid, "status", {**st, "state": "queued", "uploading": True, "updated_at": old})
    assert "업로드가 끝나지 않았습니다" in client.get("/api/reports").json()[0]["status"]["message"]
    # 방금 바뀐 '처리 중'은 그대로
    store.write(rid, "status", {**st, "state": "parsing", "updated_at": datetime.now().isoformat()})
    assert client.get(f"/api/reports/{rid}").json()["status"]["state"] == "parsing"
    # 서버 모드(PROCESS_IN_REQUEST 없음)에서는 건드리지 않는다
    monkeypatch.delenv("PROCESS_IN_REQUEST")
    store.write(rid, "status", {**st, "state": "parsing", "updated_at": old})
    assert client.get(f"/api/reports/{rid}").json()["status"]["state"] == "parsing"


# ---------- OCR: 글자를 읽을 수 없는 PDF ----------

def test_ocr_fallback_processes_unreadable_pdf(tmp_path):
    from app import ocr
    from tests.test_flow import PAGES, make_outlined_pdf

    seen = []

    def fake_ocr(png: bytes, pno: int) -> str:
        assert png[:4] == b"\x89PNG"  # 쪽 이미지가 넘어온다
        seen.append(pno)
        lines = (PAGES * 2)[pno - 1]  # 3쪽짜리 PDF: 가상 보고서 앞 3쪽 내용 (테스트용, 실제 사고 아님)
        filler = "본문 채움 문장: 테스트용 가상 보고서 쪽마다 한글이 충분히 있도록 넣은 문장입니다."
        return "\n".join(lines + [filler])

    client = _client(fake_llm)
    ocr.set_stub(fake_ocr)
    try:
        pdf = tmp_path / "scan.pdf"
        make_outlined_pdf(pdf)  # 글자 없이 선만 있는 PDF (스캔본 흉내)
        rid = client.post("/api/reports", files={"file": ("scan.pdf", pdf.read_bytes(), "application/pdf")}).json()["id"]
    finally:
        ocr.set_stub(None)
    st = client.get(f"/api/reports/{rid}").json()["status"]
    assert st["state"] == "done" and st["message"].startswith("OCR로 읽음"), st
    assert sorted(seen) == [1, 2, 3]
    parsed = store.read(rid, "parsed")
    assert parsed["ocr"] is True and parsed["pages"][1].startswith("[p.2]\n1. 사실정보")
    assert {"facts", "timeline"} <= set(parsed["sections"])


def test_ocr_needed_without_ocr_then_reprocessed_when_available(tmp_path):
    from app import ocr
    from tests.test_flow import make_outlined_pdf

    client = _client(fake_llm)
    pdf = tmp_path / "scan2.pdf"
    make_outlined_pdf(pdf)
    data = pdf.read_bytes() + b"\n% variant"  # 다른 테스트와 다른 id
    rid = client.post("/api/reports", files={"file": ("s.pdf", data, "application/pdf")}).json()["id"]
    assert client.get(f"/api/reports/{rid}").json()["status"]["state"] == "ocr_needed"  # OCR을 쓸 수 없음
    assert client.post("/api/reports", files={"file": ("s.pdf", data, "application/pdf")}).json()["new"] is False

    ocr.set_stub(lambda png, pno: "읽을 수 있는 한글이 거의 없는 쪽")  # OCR로도 한글이 부족
    try:
        again = client.post("/api/reports", files={"file": ("s.pdf", data, "application/pdf")}).json()
    finally:
        ocr.set_stub(None)
    assert again["new"] is True  # 이제 OCR을 쓸 수 있으니 다시 처리
    st = client.get(f"/api/reports/{rid}").json()["status"]
    assert st["state"] == "ocr_needed" and "OCR로도" in st["message"]
