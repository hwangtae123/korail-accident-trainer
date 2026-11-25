"""키 없이 전체 흐름을 확인하는 테스트.
가상의 보고서 PDF(내용은 테스트용으로 지어낸 것)를 만들고, 가짜 LLM으로 업로드 -> 구조화 -> 시나리오까지 돌린다.
실행: python -m pytest -q   (또는 python tests/test_flow.py)
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EMBED_PROVIDER"] = "stub"
# .env에 DATABASE_URL(Supabase)이 있어도 테스트는 로컬 파일 저장소만 쓴다 (load_dotenv는 이미 있는 값을 덮어쓰지 않는다)
os.environ["DATABASE_URL"] = ""
os.environ["VECTOR_STORE"] = "simple"

PAGES = [
    ["테스트용 가상 보고서 (실제 사고 아님)", "ARAIB/R TEST-1", "목차", "1. 사실정보", "2. 분석", "3. 결론", "4. 안전권고"],
    ["1. 사실정보", "1.1 사고 경위", "테스트 문장: 가상 장비열차가 가상 구간을 회송하였다.", "1.2 피해 상황", "테스트 피해 문장"],
    ["2. 분석", "테스트 분석 문장"],
    ["3. 결론", "3.1 조사결과", "1) 테스트 조사결과: 교육이 이론 위주로 시행되었다.", "3.2 사고원인", "테스트 직접 원인과 기여요인 ➊"],
    ["4. 안전권고", "한국철도공사는 테스트 권고를 이행할 것"],
]


def make_pdf(path: Path, tag: str = "A") -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))  # reportlab 내장 한글 폰트
    c = canvas.Canvas(str(path), pagesize=A4)
    pages = [[f"테스트용 가상 보고서 {tag} (실제 사고 아님)"] + PAGES[0][1:]] + PAGES[1:]
    for n, lines in enumerate(pages, start=1):
        c.setFont("HYGothic-Medium", 12)
        y = 800
        for line in lines + ["본문 채움 문장: 실제 보고서처럼 쪽마다 글자가 충분히 있도록 넣은 테스트용 문장입니다."]:
            c.drawString(60, y, line)
            y -= 24
        if n == 4:  # 조사결과 쪽에 격자 표 하나 (교육 실적 표 같은 것)
            cells = [["구분", "이론", "실습"], ["교육시간", "16", "2"]]
            x0, top, w, h = 60, y - 10, 120, 24
            for r, row in enumerate(cells):
                for col, val in enumerate(row):
                    c.drawString(x0 + col * w + 8, top - r * h - 17, val)
            for r in range(len(cells) + 1):
                c.line(x0, top - r * h, x0 + 3 * w, top - r * h)
            for col in range(4):
                c.line(x0 + col * w, top, x0 + col * w, top - len(cells) * h)
        c.drawCentredString(A4[0] / 2, 30, f"- {n} -")  # 쪽번호
        c.showPage()
    c.save()


def fake_llm(system: str, user: str) -> str:
    ev = {"page": 4, "quote": "테스트"}
    if "안전 담당자를 돕는 분석가" in system:
        assert "테스트용 가상 보고서" in user  # 검색 결과가 컨텍스트로 들어갔는지
        return "테스트 요약 [테스트용 가상 보고서 p.4]"
    if "구조화하는 분석가" in system:
        tag = re.search(r"가상 보고서 (\w)", user).group(1)
        return json.dumps({
            "report_no": f"ARAIB/R TEST-{tag}", "title": f"테스트용 가상 보고서 {tag}", "accident_type": "탈선",
            "summary": "테스트 요약", "timeline": [{"event": "테스트 경위", "evidence": ev}],
            "direct_causes": [{"text": "테스트 직접 원인", "evidence": ev}],
            "violated_rules": [{"rule_name": "테스트지침", "description": "테스트", "evidence": ev}],
            "training_findings": [{"text": "교육이 이론 위주", "evidence": ev}],
        }, ensure_ascii=False)
    return "```json\n" + json.dumps({
        "title": "테스트 시나리오", "role": "테스트 역할", "intro": "테스트 도입",
        "steps": [{"situation": "테스트 상황", "question": "어떻게 하겠는가?",
                   "options": [{"id": "A", "text": "정답"}, {"id": "B", "text": "오답"}],
                   "answer_id": "A", "explanation": "테스트 해설", "what_happened": "테스트 결과", "evidence": ev}],
        "debrief": "테스트 마무리",
    }, ensure_ascii=False) + "\n```"


def test_parse_sections():
    from app.parse import parse_report

    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "t.pdf"
        make_pdf(pdf)
        r = parse_report(pdf)
    assert len(r.pages) == 5
    for key in ["facts", "timeline", "analysis", "conclusion", "findings", "causes", "recommendations"]:
        assert key in r.sections, key
    # 목차의 제목이 아니라 본문 위치를 잡았는지, 경위가 1.2 전에서 끊기는지
    assert "[p.2]" in r.sections["timeline"] and "피해 상황" not in r.sections["timeline"]
    assert "[p.4]" in r.sections["findings"] and "사고원인" not in r.sections["findings"]
    assert "테스트 권고" in r.sections["recommendations"]
    # 쪽번호는 빠지고, 표는 본문에서 분리돼 Markdown으로 붙는다
    assert "- 4 -" not in r.pages[3]
    assert "| 교육시간 | 16 | 2 |" in r.pages[3]
    body_part = r.pages[3].split("[표 p.4-1]")[0]
    assert "교육시간" not in body_part


def test_api_flow():
    from fastapi.testclient import TestClient

    from app import llm
    from app.main import app

    llm.set_stub(fake_llm)
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "t.pdf"
        make_pdf(pdf)
        first_bytes = pdf.read_bytes()
        res = client.post("/api/reports", files={"file": ("t.pdf", first_bytes, "application/pdf")})
    assert res.status_code == 200, res.text
    rid = res.json()["id"]  # TestClient는 BackgroundTasks를 응답 후 바로 실행한다

    detail = client.get(f"/api/reports/{rid}").json()
    assert detail["status"]["state"] == "done", detail["status"]
    assert detail["record"]["violated_rules"][0]["rule_name"] == "테스트지침"

    sc = client.get(f"/api/reports/{rid}/scenario").json()
    assert sc["review_status"] == "검수 전" and sc["steps"][0]["answer_id"] == "A"
    assert client.post(f"/api/reports/{rid}/scenario/review").json()["ok"]
    assert client.get(f"/api/reports/{rid}/scenario").json()["review_status"] == "검수 완료"

    stats = client.get("/api/stats").json()
    assert stats["reports"] == 1 and stats["violated_rules"][0] == {"name": "테스트지침", "count": 1}
    # 유사사고 검색 (ChromaDB, stub 임베딩)
    hits = client.post("/api/search", json={"q": "테스트 직접 원인"}).json()
    assert hits and hits[0]["report_id"] == rid
    kinds = {h["kind"] for h in hits[0]["hits"]}
    assert "직접원인" in kinds, kinds
    ans = client.post("/api/ask", json={"q": "테스트 직접 원인"}).json()
    assert "p.4" in ans["answer"]
    # 다시 색인해도 중복되지 않는다
    from app import search
    before = search._collection().count()
    client.post("/api/reindex")
    assert search._collection().count() == before

    assert client.get("/api/health").json() == {"ok": True}
    assert client.post("/api/reports", files={"file": ("x.pdf", b"not pdf", "application/pdf")}).status_code == 400

    # ---- 새 보고서가 들어오면 과거 사고와 바로 연결된다 ----
    with tempfile.TemporaryDirectory() as d:
        b = Path(d) / "b.pdf"
        make_pdf(b, "B")
        dup = client.post("/api/reports", files={"file": ("a.pdf", first_bytes, "application/pdf")}).json()
        assert dup == {"id": rid, "new": False}  # 같은 파일은 다시 처리하지 않는다
        new = client.post("/api/reports", files={"file": ("b.pdf", b.read_bytes(), "application/pdf")}).json()
    assert new["new"] and new["id"] != rid
    rel = client.get(f"/api/reports/{new['id']}/related").json()
    assert [g["report_id"] for g in rel] == [rid]  # 자기 자신은 빠지고 과거 사고(A)가 나온다
    assert rel[0]["shared_rules"] == ["테스트지침"]
    assert "p.4" in client.post(f"/api/reports/{new['id']}/compare").json()["answer"]
    assert client.get("/api/reports").json()[0]["id"] == new["id"]  # 새로 들어온 게 목록 맨 위


def make_outlined_pdf(path: Path) -> None:
    """글자 없이 선만 있는 PDF (글자를 도형으로 그린 보고서 흉내)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for _ in range(3):
        for i in range(200):
            c.line(60, 800 - i * 3, 400, 800 - i * 3)
        c.showPage()
    c.save()


def test_ocr_needed_skips_llm():
    from fastapi.testclient import TestClient

    from app import llm
    from app.main import app

    def must_not_call(system, user):
        raise AssertionError("텍스트 없는 PDF로 LLM을 부르면 안 된다")

    llm.set_stub(must_not_call)
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "scan.pdf"
        make_outlined_pdf(pdf)
        rid = client.post("/api/reports", files={"file": ("scan.pdf", pdf.read_bytes(), "application/pdf")}).json()["id"]
    st = client.get(f"/api/reports/{rid}").json()["status"]
    assert st["state"] == "ocr_needed", st
    llm.set_stub(fake_llm)


def test_inbox_watch():
    from app import llm, store, watch

    llm.set_stub(fake_llm)
    watch.POLL_SEC = 0.2
    inbox = Path(tempfile.mkdtemp())
    stop = watch.start(str(inbox))
    try:
        tmp = Path(tempfile.mkdtemp()) / "c.pdf"
        make_pdf(tmp, "C")
        shutil.copy(tmp, inbox / "c.pdf")  # 크롤러가 새 보고서를 떨어뜨린 상황
        rid = store.report_id(tmp.read_bytes())
        for _ in range(100):
            if (store.read(rid, "status") or {}).get("state") == "done":
                break
            time.sleep(0.1)
        assert store.read(rid, "status")["state"] == "done"
        assert store.read(rid, "record")["title"] == "테스트용 가상 보고서 C"
    finally:
        stop.set()


if __name__ == "__main__":
    test_parse_sections()
    test_api_flow()
    test_ocr_needed_skips_llm()
    test_inbox_watch()
    print("ok")
