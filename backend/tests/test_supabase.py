"""Supabase 연동 시험 (실제 DB에 접속). 평소에는 건너뛴다.

돌리는 법 (backend/에서, schema.sql을 먼저 적용한 프로젝트에 대해):
  PowerShell:  $env:TEST_DATABASE_URL = "<DATABASE_URL과 같은 값>"; python -m pytest -q tests/test_supabase.py
  Storage까지:  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 도 환경변수로
만든 행은 'zztest-'로 시작하는 id를 쓰고, 끝나면 지운다.
"""
import os
import uuid

import pytest

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
