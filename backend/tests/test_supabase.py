"""Supabase 연동 시험 (실제 DB에 접속). 평소에는 건너뛴다.

돌리는 법 (backend/에서, schema.sql을 먼저 적용한 프로젝트에 대해):
  PowerShell:  $env:TEST_DATABASE_URL = "<DATABASE_URL과 같은 값>"; python -m pytest -q tests/test_supabase.py
  Storage까지:  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 도 환경변수로
만든 행은 'zztest-'로 시작하는 id를 쓰고, 끝나면 지운다.
"""
import os
import uuid

import pytest

from tests.test_flow import fake_llm, make_pdf  # 먼저 불러 둔다 (모듈이 처음 불릴 때 DATABASE_URL을 비우므로)

from app import db, store
from app.vectorstore import PgCollection

TEST_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL 없음 — Supabase 연동 시험 건너뜀")


@pytest.fixture()
def supa(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "cache")
    db.reset_pool()
    rid = f"zztest-{uuid.uuid4().hex[:8]}"
    yield rid
    db.run("delete from public.reports where id like 'zztest-%'")
    db.reset_pool()


def test_documents_roundtrip(supa):
    rid = supa
    assert store.backend() == "supabase"
    store.set_status(rid, "queued", "대기 중", filename="테스트용 가상 보고서.pdf")
    store.write(rid, "record", {"title": "테스트용 가상 보고서", "violated_rules": [{"rule_name": "테스트지침"}]})
    assert store.read(rid, "status")["state"] == "queued"
    assert store.read(rid, "record")["violated_rules"][0]["rule_name"] == "테스트지침"
    assert store.read(rid, "scenario") is None
    store.set_status(rid, "done", "끝")
    st = store.read(rid, "status")
    assert st["state"] == "done" and st["filename"] == "테스트용 가상 보고서.pdf"
    assert rid in store.list_ids()
    docs = dict(store.iter_docs("status", "record"))
    assert docs[rid]["record"]["title"] == "테스트용 가상 보고서"
    assert db.run("select state, filename from public.reports where id = :id", id=rid)[0] == ["done", "테스트용 가상 보고서.pdf"]


def test_pgvector_collection(supa):
    rid = supa
    store.set_status(rid, "done", "")
    col = PgCollection()
    col.add([f"{rid}:0", f"{rid}:1"], ["가 조각", "나 조각"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            [{"report_id": rid, "title": "t", "kind": "본문", "page": 3},
             {"report_id": rid, "title": "t", "kind": "개요", "page": -1}])
    res = col.query([[0.9, 0.1, 0.0]], n_results=2, where={"report_id": rid})
    assert res["ids"][0] == [f"{rid}:0", f"{rid}:1"]
    assert res["metadatas"][0][0]["page"] == 3 and res["metadatas"][0][1]["page"] == -1
    assert res["distances"][0][0] < res["distances"][0][1]
    other = col.query([[1.0, 0.0, 0.0]], n_results=50, where={"report_id": {"$ne": rid}})
    assert not any(i.startswith(rid) for i in other["ids"][0])
    col.delete(where={"report_id": rid})
    assert col.query([[1.0, 0.0, 0.0]], where={"report_id": rid})["ids"][0] == []


@pytest.mark.skipif(not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
                    reason="SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 없음")
def test_pdf_storage(supa, tmp_path, monkeypatch):
    rid = supa
    data = b"%PDF-1.4 test-only fake pdf " + rid.encode()
    store.save_pdf(rid, data)
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "other-instance")  # 다른 서버 인스턴스: 로컬 캐시 없음
    p = store.local_pdf(rid)
    assert p is not None and p.read_bytes() == data
    from app import supa_storage

    base, key, bucket = supa_storage._conf()
    import httpx

    httpx.delete(f"{base}/storage/v1/object/{bucket}/{rid}/report.pdf",
                 headers={"Authorization": f"Bearer {key}", "apikey": key})


@pytest.mark.skipif(not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
                    reason="SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 없음")
def test_direct_upload_flow(supa, tmp_path, monkeypatch):
    """Vercel 방식: upload-url -> Storage에 PUT -> process (요청 안에서 끝까지). 가짜 LLM, 1536차원 가짜 임베딩."""
    import httpx
    from fastapi.testclient import TestClient

    from app import llm, search, supa_storage
    from app.main import app

    monkeypatch.setenv("PROCESS_IN_REQUEST", "1")
    monkeypatch.setenv("STUB_EMBED_DIM", "1536")
    monkeypatch.setenv("VECTOR_STORE", "auto")
    search.reset_client()
    llm.set_stub(fake_llm)
    pdf = tmp_path / "direct.pdf"
    make_pdf(pdf, "D")
    data = pdf.read_bytes()
    rid = store.report_id(data)
    client = TestClient(app)
    try:
        assert client.get("/api/config").json()["direct_upload"] is True
        r = client.post("/api/reports/upload-url", json={"id": rid, "filename": "테스트용 가상 보고서 D.pdf"}).json()
        assert r["new"] and r["upload_url"]
        assert client.get(f"/api/reports/{rid}").json()["status"]["state"] == "queued"
        assert httpx.put(r["upload_url"], content=data, headers={"Content-Type": "application/pdf"}, timeout=60).status_code == 200
        st = client.post(f"/api/reports/{rid}/process", json={"filename": "테스트용 가상 보고서 D.pdf"}).json()
        assert st["state"] == "done", st
        assert client.get(f"/api/reports/{rid}").json()["record"]["title"] == "테스트용 가상 보고서 D"
        assert db.run("select count(*) from public.report_chunks where report_id = :r", r=rid)[0][0] > 0
        # 같은 파일을 다시 올리면 new=false
        assert client.post("/api/reports/upload-url", json={"id": rid, "filename": "x.pdf"}).json()["new"] is False
    finally:
        db.run("delete from public.reports where id = :r", r=rid)
        base, key, bucket = supa_storage._conf()
        httpx.delete(f"{base}/storage/v1/object/{bucket}/{rid}/report.pdf",
                     headers={"Authorization": f"Bearer {key}", "apikey": key})
        search.reset_client()


def test_many_concurrent_queries(supa, monkeypatch):
    """Transaction pooler(6543)에서 동시 쿼리가 많아도 'unnamed prepared statement' 오류가 나지 않는다 (쿼리마다 트랜잭션)."""
    import threading

    monkeypatch.setenv("DB_POOL_SIZE", "12")
    db.reset_pool()
    errs = []

    def worker(k):
        for i in range(10):
            try:
                if i % 2:
                    db.run("select count(*) from public.reports where id = :a", a=f"x{k}")
                else:
                    db.run("select count(*) from public.reports where id = :a or id = :b or state = :c", a="x", b="y", c="z")
            except Exception as e:  # noqa: BLE001
                errs.append(str(e)[:120])

    ts = [threading.Thread(target=worker, args=(k,)) for k in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs, errs[:3]
