"""ChromaDB를 쓸 수 없는 환경을 위한 대체 벡터 저장소 (numpy, 로컬 파일).

search.py가 쓰는 Chroma Collection 기능만 똑같은 모양으로 흉내 낸다:
count / add / delete(where) / query(query_embeddings, n_results, where).
보고서 수백 건, 조각 수만 개 정도까지는 전부 메모리에 올려 코사인 유사도를 계산해도 충분히 빠르다.

어떤 저장소를 쓸지는 search.py의 VECTOR_STORE 환경변수가 정한다 (chroma | simple | auto).
"""
import json
import os
import threading
from pathlib import Path

import numpy as np


def _match(meta: dict, where: dict | None) -> bool:
    if not where:
        return True
    for key, cond in where.items():
        val = meta.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$eq" and val != arg:
                    return False
                if op == "$ne" and val == arg:
                    return False
                if op == "$in" and val not in arg:
                    return False
                if op == "$nin" and val in arg:
                    return False
        elif val != cond:
            return False
    return True


class SimpleCollection:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.ids: list[str] = []
        self.documents: list[str] = []
        self.metadatas: list[dict] = []
        self.emb = np.zeros((0, 0), dtype=np.float32)
        self._stamp = None
        self._load()

    # ---------- 저장 ----------

    def _files(self) -> tuple[Path, Path]:
        return self.path / "items.json", self.path / "embeddings.npy"

    def _file_stamp(self):
        meta_p, emb_p = self._files()
        # 수정 시각만으로는 부족하다 (Windows는 시각 해상도가 ~15ms라 연달아 쓴 두 번이 같은 값일 수 있음).
        # 저장은 항상 새 파일로 바꿔치기(os.replace)하므로 파일 ID(st_ino)가 매번 바뀐다.
        try:
            return tuple((s.st_ino, s.st_mtime_ns, s.st_size) for s in (meta_p.stat(), emb_p.stat()))
        except FileNotFoundError:
            return None

    def _refresh(self) -> None:
        """다른 프로세스(scripts/ingest.py 등)가 파일을 바꿨으면 다시 읽는다."""
        if self._file_stamp() != self._stamp:
            self._load()

    def _load(self) -> None:
        meta_p, emb_p = self._files()
        self._stamp = self._file_stamp()
        if not meta_p.exists() or not emb_p.exists():
            return
        data = json.loads(meta_p.read_text(encoding="utf-8"))
        emb = np.load(emb_p)
        if len(data["ids"]) != len(emb):  # 저장 도중 꺼진 경우: 비우고 다시 색인하게 둔다
            return
        self.ids, self.documents, self.metadatas = data["ids"], data["documents"], data["metadatas"]
        self.emb = emb.astype(np.float32)

    def _save(self) -> None:
        meta_p, emb_p = self._files()
        tag = f"{os.getpid()}.{threading.get_ident()}"
        tmp_meta = meta_p.with_suffix(f".{tag}.tmp")
        tmp_emb = self.path / f"embeddings.{tag}.tmp.npy"
        tmp_meta.write_text(json.dumps({"ids": self.ids, "documents": self.documents,
                                        "metadatas": self.metadatas}, ensure_ascii=False), encoding="utf-8")
        np.save(tmp_emb, self.emb)
        os.replace(tmp_emb, emb_p)
        os.replace(tmp_meta, meta_p)
        self._stamp = self._file_stamp()

    # ---------- Chroma Collection과 같은 모양 ----------

    def count(self) -> int:
        with self._lock:
            self._refresh()
            return len(self.ids)

    def add(self, ids: list[str], documents: list[str], embeddings: list[list[float]], metadatas: list[dict]) -> None:
        new = np.asarray(embeddings, dtype=np.float32)
        if new.ndim != 2 or len(new) != len(ids):
            raise ValueError("embeddings 개수가 ids와 다릅니다")
        norms = np.linalg.norm(new, axis=1, keepdims=True)
        new = new / np.where(norms == 0, 1, norms)
        with self._lock:
            self._refresh()
            if self.count() and self.emb.shape[1] != new.shape[1]:
                raise RuntimeError(
                    f"임베딩 차원이 다릅니다 (저장 {self.emb.shape[1]}, 새 {new.shape[1]}). "
                    f"EMBED_MODEL을 바꿨다면 {self.path}를 지우고 /api/reindex 하세요.")
            keep = [i for i, x in enumerate(self.ids) if x not in set(ids)]
            self._keep(keep)
            self.ids += list(ids)
            self.documents += list(documents)
            self.metadatas += [dict(m) for m in metadatas]
            self.emb = new if self.emb.size == 0 else np.vstack([self.emb, new])
            self._save()

    def delete(self, where: dict | None = None, ids: list[str] | None = None) -> None:
        with self._lock:
            self._refresh()
            drop = set(ids or [])
            keep = [i for i, (x, m) in enumerate(zip(self.ids, self.metadatas))
                    if not (x in drop or (where is not None and _match(m, where)))]
            if len(keep) != self.count():
                self._keep(keep)
                self._save()

    def _keep(self, idx: list[int]) -> None:
        self.ids = [self.ids[i] for i in idx]
        self.documents = [self.documents[i] for i in idx]
        self.metadatas = [self.metadatas[i] for i in idx]
        self.emb = self.emb[idx] if self.emb.size else self.emb

    def query(self, query_embeddings: list[list[float]], n_results: int = 10, where: dict | None = None) -> dict:
        out = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        with self._lock:
            self._refresh()
            cand = [i for i, m in enumerate(self.metadatas) if _match(m, where)]
            mat = self.emb[cand] if cand else None
            for q in query_embeddings:
                if mat is None:
                    for k in out:
                        out[k].append([])
                    continue
                v = np.asarray(q, dtype=np.float32)
                v = v / (np.linalg.norm(v) or 1.0)
                sims = mat @ v
                order = np.argsort(-sims)[:n_results]
                out["ids"].append([self.ids[cand[j]] for j in order])
                out["documents"].append([self.documents[cand[j]] for j in order])
                out["metadatas"].append([self.metadatas[cand[j]] for j in order])
                out["distances"].append([float(1 - sims[j]) for j in order])
        return out


class PgCollection:
    """Supabase pgvector (public.report_chunks). SimpleCollection과 같은 모양.
    metadatas의 report_id·title·kind·page는 테이블 칸으로 저장한다 (page -1 = 쪽 번호 없음)."""

    def __init__(self):
        from . import db

        self.db = db

    @staticmethod
    def _vec(v) -> str:
        return "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"

    @staticmethod
    def _where_sql(where: dict | None) -> tuple[str, dict]:
        if not where:
            return "", {}
        (key, cond), = where.items()  # search.py는 report_id 조건 하나만 쓴다
        if key != "report_id":
            raise ValueError(f"지원하지 않는 where: {where}")
        if isinstance(cond, dict):
            (op, arg), = cond.items()
            if op == "$ne":
                return "where report_id <> :w", {"w": arg}
            if op == "$eq":
                return "where report_id = :w", {"w": arg}
            raise ValueError(f"지원하지 않는 where: {where}")
        return "where report_id = :w", {"w": cond}

    def count(self) -> int:
        return int(self.db.run("select count(*) from public.report_chunks")[0][0])

    def add(self, ids: list[str], documents: list[str], embeddings: list[list[float]], metadatas: list[dict]) -> None:
        """한 보고서의 조각 수십 개를 쿼리 한 번으로 넣는다 (unnest)."""
        if not ids:
            return
        pages = [m.get("page") for m in metadatas]
        self.db.run(
            "insert into public.report_chunks (id, report_id, title, kind, page, text, embedding) "
            "select i, r, t, k, p, x, cast(e as vector) from unnest("
            "cast(:ids as text[]), cast(:rids as text[]), cast(:titles as text[]), cast(:kinds as text[]), "
            "cast(cast(:pages as text[]) as int[]), cast(:texts as text[]), cast(:embs as text[])) as u(i, r, t, k, p, x, e) "
            "on conflict (id) do update set report_id = excluded.report_id, title = excluded.title, "
            "kind = excluded.kind, page = excluded.page, text = excluded.text, embedding = excluded.embedding",
            ids=list(ids), rids=[m["report_id"] for m in metadatas], titles=[m.get("title", "") for m in metadatas],
            kinds=[m.get("kind", "") for m in metadatas],
            pages=[None if pg is None or pg < 0 else str(int(pg)) for pg in pages],  # text[]로 보내 int[]로 변환 (전부 null이어도 타입이 정해지게)
            texts=list(documents), embs=[self._vec(e) for e in embeddings])

    def delete(self, where: dict | None = None, ids: list[str] | None = None) -> None:
        if ids:
            self.db.run("delete from public.report_chunks where id = any(cast(:ids as text[]))", ids=list(ids))
        if where is not None:
            sql, params = self._where_sql(where)
            self.db.run(f"delete from public.report_chunks {sql}", **params)

    def query(self, query_embeddings: list[list[float]], n_results: int = 10, where: dict | None = None) -> dict:
        out = {"ids": [], "documents": [], "metadatas": [], "distances": []}
        cond, params = self._where_sql(where)
        for q in query_embeddings:
            rows = self.db.run(
                "select id, text, report_id, title, kind, page, embedding <=> cast(:q as vector) as dist "
                # 차원이 다른 조각(임베딩 모델을 바꾸기 전 것)은 비교할 수 없으므로 뺀다 (섞여 있으면 pgvector가 오류를 낸다)
                f"from public.report_chunks {cond} {'and' if cond else 'where'} vector_dims(embedding) = :dims "
                "order by dist limit :n",
                q=self._vec(q), n=int(n_results), dims=len(q), **params)
            out["ids"].append([r[0] for r in rows])
            out["documents"].append([r[1] for r in rows])
            out["metadatas"].append([{"report_id": r[2], "title": r[3], "kind": r[4],
                                      "page": r[5] if r[5] is not None else -1} for r in rows])
            out["distances"].append([float(r[6]) for r in rows])
        return out
