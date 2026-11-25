"""유사사고 검색: 구조화 결과와 본문 조각을 ChromaDB(로컬 파일)에 넣고, 상황 설명으로 비슷한 과거 사고를 찾는다.

임베딩은 직접 계산해서 넣는다 (Chroma 내장 임베딩 함수 대신). 공급자는 환경변수로 바꾼다.
EMBED_PROVIDER=openai (기본)  EMBED_MODEL=text-embedding-3-small
EMBED_PROVIDER=stub           키 없이 테스트 (글자 n-gram 해시)

벡터 저장소는 VECTOR_STORE 환경변수로 고른다.
VECTOR_STORE=auto (기본)   DATABASE_URL이 있으면 pgvector, 아니면 chromadb를 import할 수 있으면 ChromaDB, 아니면 simple
VECTOR_STORE=pgvector      Supabase public.report_chunks (app/vectorstore.py PgCollection)
VECTOR_STORE=chroma        ChromaDB (data/chroma, pip install chromadb 필요)
VECTOR_STORE=simple        numpy 대체 저장소 (data/vectors, app/vectorstore.py)
  ※ Windows에서 VC++ 재배포 패키지가 없거나 '스마트 앱 컨트롤'이 grpc DLL을 막으면 chromadb import가 실패한다.
"""
import hashlib
import math
import os
import re
from collections import defaultdict

from . import store
from .rule_aliases import canonical_key

COLLECTION = "accidents"
CHUNK = 700
OVERLAP = 100
_client = None
_col = None
backend_name = ""  # 실제로 쓰는 저장소 (pgvector | chroma | simple)


def _collection():
    global _client, _col, backend_name
    if _col is not None:
        return _col if backend_name != "chroma" else _client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"})
    choice = os.getenv("VECTOR_STORE", "auto").lower()
    if choice == "pgvector" or (choice == "auto" and store.backend() == "supabase"):
        from .vectorstore import PgCollection

        _col = PgCollection()
        backend_name = "pgvector"
        return _col
    if choice in ("auto", "chroma"):
        try:
            import chromadb

            _client = chromadb.PersistentClient(path=str(store.DATA_DIR / "chroma"))
            _col = _client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
            backend_name = "chroma"
            return _col
        except ImportError as e:
            if choice == "chroma":
                raise
            print(f"[search] chromadb를 쓸 수 없어 simple 저장소로 대신함: {e}", flush=True)
    elif choice not in ("simple", "pgvector"):
        raise RuntimeError(f"알 수 없는 VECTOR_STORE: {choice}")
    from .vectorstore import SimpleCollection

    _col = SimpleCollection(store.DATA_DIR / "vectors")
    backend_name = "simple"
    return _col


def reset_client() -> None:  # 테스트에서 DATA_DIR를 바꿀 때
    global _client, _col, backend_name
    _client = _col = None
    backend_name = ""


# ---------- 임베딩 ----------

def _stub_embed(text: str, dim: int = 256) -> list[float]:
    v = [0.0] * dim
    s = re.sub(r"\s+", "", text)
    for i in range(len(s) - 1):
        h = int(hashlib.md5(s[i:i + 2].encode()).hexdigest(), 16)
        v[h % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(texts: list[str]) -> list[list[float]]:
    provider = os.getenv("EMBED_PROVIDER", "openai").lower()
    if provider == "stub":
        return [_stub_embed(t) for t in texts]
    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(base_url=os.getenv("EMBED_BASE_URL") or None)
        model = os.getenv("EMBED_MODEL", "text-embedding-3-small")
        out = []
        for i in range(0, len(texts), 100):
            resp = client.embeddings.create(model=model, input=texts[i:i + 100])
            out += [d.embedding for d in resp.data]
        return out
    raise RuntimeError(f"알 수 없는 EMBED_PROVIDER: {provider}")


# ---------- 색인 ----------

def _page_chunks(section: str) -> list[tuple[str, int | None]]:
    """[p.N] 표시를 따라가며 쪽 번호를 기억하고, 글자 수 기준으로 자른다.
    Markdown 표 줄("| … |")과 표 제목 줄("[표 …]")은 뺀다: 칸 나열이라 검색을 흐리고 화면 조각으로도 읽히지 않는다."""
    out, buf, page, buf_page = [], "", None, None
    for line in section.split("\n"):
        m = re.match(r"^\[p\.(\d+)\]$", line.strip())
        if m:
            page = int(m.group(1))
            continue
        if line.lstrip().startswith("|") or re.match(r"^\s*\[표", line):
            continue
        if not buf:
            buf_page = page
        buf += line + "\n"
        if len(buf) >= CHUNK:
            out.append((buf.strip(), buf_page))
            buf = buf[-OVERLAP:]
            buf_page = page
    if buf.strip():
        out.append((buf.strip(), buf_page))
    return out


def _docs(rid: str, record: dict, sections: dict) -> list[dict]:
    title = record.get("title", "")
    head = f"[{record.get('accident_type', '')}] {title} / {record.get('location', '')}"
    docs = [{"kind": "개요", "text": f"{head}\n{record.get('summary', '')}", "page": None}]
    if record.get("timeline"):
        docs.append({"kind": "경위", "text": "\n".join(t["event"] for t in record["timeline"]),
                     "page": record["timeline"][0].get("evidence", {}).get("page")})
    for key, kind, field in [("direct_causes", "직접원인", "text"), ("contributing_factors", "기여요인", "text"),
                             ("training_findings", "교육지적", "text"), ("recommendations", "안전권고", "text")]:
        for it in record.get(key, []):
            docs.append({"kind": kind, "text": it[field], "page": it.get("evidence", {}).get("page")})
    for r in record.get("violated_rules", []):
        docs.append({"kind": "규정", "text": f"{r['rule_name']} {r.get('article', '')}: {r['description']}",
                     "page": r.get("evidence", {}).get("page")})
    for sec in ("findings", "analysis"):
        for text, page in _page_chunks(sections.get(sec, "")):
            docs.append({"kind": "본문", "text": text, "page": page})
    for d in docs:
        d.update(report_id=rid, title=title)
    return [d for d in docs if d["text"].strip()]


def index_report(rid: str) -> int:
    record, parsed = store.read(rid, "record"), store.read(rid, "parsed")
    col = _collection()
    col.delete(where={"report_id": rid})  # 다시 처리할 때 중복 방지
    docs = _docs(rid, record, parsed.get("sections", {}))
    if not docs:
        return 0
    col.add(
        ids=[f"{rid}:{i}" for i in range(len(docs))],
        documents=[d["text"] for d in docs],
        embeddings=embed([d["text"] for d in docs]),
        metadatas=[{"report_id": d["report_id"], "title": d["title"], "kind": d["kind"],
                    "page": d["page"] if d["page"] is not None else -1} for d in docs],
    )
    return len(docs)


# ---------- 검색 ----------

def search(query: str, n_reports: int = 5, hits_per_report: int = 4, exclude: str | None = None) -> list[dict]:
    """상황 설명 -> 비슷한 사고 보고서 (보고서별로 묶고, 가장 가까운 조각 점수로 정렬)."""
    col = _collection()
    if col.count() == 0:
        return []
    where = {"report_id": {"$ne": exclude}} if exclude else None
    res = col.query(query_embeddings=embed([query]), n_results=min(60, col.count()), where=where)
    grouped: dict[str, dict] = defaultdict(lambda: {"score": 0.0, "hits": []})
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        g = grouped[meta["report_id"]]
        sim = round(1 - dist, 3)
        g["report_id"], g["title"] = meta["report_id"], meta["title"]
        g["score"] = max(g["score"], sim)
        if len(g["hits"]) < hits_per_report:
            g["hits"].append({"kind": meta["kind"], "text": doc, "score": sim,
                              "page": meta["page"] if meta["page"] > 0 else None})
    return sorted(grouped.values(), key=lambda g: -g["score"])[:n_reports]


# ---------- 새 보고서 -> 과거 사고 연결 ----------

def _norm_rule(name: str) -> str:
    """표기만 다른 같은 규정을 같은 키로 (app/rule_aliases.py, BE-4)."""
    return canonical_key(name)


def record_query(record: dict) -> str:
    """새 사고를 과거 사고와 비교할 때 쓰는 질의: 개요 + 원인 + 기여요인 + 지적된 규정."""
    parts = [record.get("summary", "")]
    parts += [c["text"] for c in record.get("direct_causes", [])]
    parts += [c["text"] for c in record.get("contributing_factors", [])]
    parts += [f"{r['rule_name']} {r['description']}" for r in record.get("violated_rules", [])]
    return "\n".join(p for p in parts if p)


def related(rid: str, n: int = 3) -> list[dict]:
    """새로 들어온 보고서와 비슷한 과거 사고 + 이번에도 반복된 규정(이름이 같은 것)."""
    record = store.read(rid, "record") or {}
    mine = {_norm_rule(r["rule_name"]): r["rule_name"] for r in record.get("violated_rules", [])}
    groups = search(record_query(record), n_reports=n, hits_per_report=3, exclude=rid)
    for g in groups:
        other = store.read(g["report_id"], "record") or {}
        theirs = {_norm_rule(r["rule_name"]) for r in other.get("violated_rules", [])}
        g["shared_rules"] = [mine[k] for k in mine if k in theirs]
        g["accident_type"] = other.get("accident_type", "")
        g["occurred_at"] = other.get("occurred_at", "")
    return groups


ASK_SYSTEM = """당신은 철도 안전 담당자를 돕는 분석가입니다. 사용자가 설명한 작업·상황과 비슷한 과거 사고조사 결과가 주어집니다.
규칙:
- 주어진 검색 결과에 있는 내용만 쓰세요. 없는 사실을 만들지 마세요.
- 문장마다 근거를 [보고서 제목 p.N] 형식으로 붙이세요 (쪽 번호가 없으면 제목만).
- 구성: 1) 비슷한 과거 사고 2) 반복된 원인·규정 위반 3) 이 상황에서 확인할 점 (과거 안전권고 기준)
- 검색 결과가 상황과 거리가 멀면 그렇다고 말하세요.
- 짧게, 개조식으로."""


def ask(query: str, exclude: str | None = None) -> dict:
    from .llm import complete_text

    groups = search(query, exclude=exclude)
    if not groups:
        return {"answer": "색인된 보고서가 없습니다.", "groups": []}
    ctx = []
    for g in groups:
        ctx.append(f"## {g['title']} (유사도 {g['score']})")
        for h in g["hits"]:
            pg = f" p.{h['page']}" if h["page"] else ""
            ctx.append(f"- [{h['kind']}{pg}] {h['text'][:600]}")
    answer = complete_text(ASK_SYSTEM, f"## 상황\n{query}\n\n## 검색 결과\n" + "\n".join(ctx))
    return {"answer": answer, "groups": groups}
