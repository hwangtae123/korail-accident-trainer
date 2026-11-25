"""저장소. 보고서마다 status / parsed / record / scenario 네 문서와 원문 PDF를 둔다.

DATABASE_URL이 있으면 Supabase:  public.reports 테이블 (문서마다 jsonb 칸) + Storage 버킷 (PDF)
없으면 로컬 파일:              data/<id>/<이름>.json + data/<id>/report.pdf   (개발·테스트용, 키 없이 돈다)

어느 쪽이든 data/<id>/ 는 로컬 작업 폴더로 쓴다 (PDF 캐시, 레이아웃 파서 작업 폴더).
어느 저장소를 쓸지는 호출할 때마다 정한다 (.env를 늦게 읽어도 되도록).
"""
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from . import db

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
NAMES = ("status", "parsed", "record", "scenario")
PDF_NAME = "report.pdf"


def backend() -> str:
    return "supabase" if db.enabled() else "file"


def report_id(pdf_bytes: bytes) -> str:
    return hashlib.sha1(pdf_bytes).hexdigest()[:10]


def rdir(rid: str) -> Path:
    """로컬 작업 폴더 (파일 저장소에서는 데이터 폴더이기도 하다)."""
    d = DATA_DIR / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _file_lock(p: Path) -> threading.Lock:
    """같은 파일의 읽기와 바꿔치기를 한 프로세스 안에서 차례로 한다 (Windows는 열려 있는 파일을 바꿔치기하지 못한다)."""
    key = str(p)
    with _file_locks_guard:
        return _file_locks.setdefault(key, threading.Lock())


def _retry_win(fn, tries: int = 20):
    """Windows에서는 다른 스레드가 파일을 열고 있는 순간 바꿔치기(os.replace)·열기가 PermissionError로 실패한다.
    (처리 스레드가 status를 쓰는 동안 화면 폴링이 같은 파일을 읽는 경우) 잠깐 기다렸다 다시 한다."""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.02 * (i + 1))


def _check(name: str) -> None:
    if name not in NAMES:
        raise ValueError(f"알 수 없는 문서 이름: {name}")


# ---------- 문서 읽기·쓰기 ----------

def write(rid: str, name: str, obj) -> None:
    _check(name)
    if db.enabled():
        if name == "status":
            db.run(
                "insert into public.reports (id, status, state, filename) "
                "values (:id, cast(:v as jsonb), :state, :filename) "
                "on conflict (id) do update set status = excluded.status, state = excluded.state, "
                "filename = case when excluded.filename <> '' then excluded.filename else public.reports.filename end, "
                "updated_at = now()",
                id=rid, v=db.jsonb(obj), state=obj.get("state", ""), filename=obj.get("filename", ""))
        else:
            db.run(f"insert into public.reports (id, {name}) values (:id, cast(:v as jsonb)) "
                   f"on conflict (id) do update set {name} = excluded.{name}, updated_at = now()",
                   id=rid, v=db.jsonb(obj))
        return
    # 임시 파일에 쓰고 바꿔치기한다. 처리 스레드가 쓰는 도중 화면 폴링이 반쯤 쓰인 JSON을 읽지 않도록.
    target = rdir(rid) / f"{name}.json"
    tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    with _file_lock(target):
        _retry_win(lambda: os.replace(tmp, target))  # 다른 프로세스(scripts/ingest.py 등)가 읽는 중이면 잠깐 기다림


def _val(v):
    return json.loads(v) if isinstance(v, str) else v


def read(rid: str, name: str):
    _check(name)
    if db.enabled():
        rows = db.run(f"select {name} from public.reports where id = :id", id=rid)
        return _val(rows[0][0]) if rows else None
    p = DATA_DIR / rid / f"{name}.json"
    if not p.exists():
        return None
    try:
        with _file_lock(p):
            text = _retry_win(lambda: p.read_text(encoding="utf-8"))
        return json.loads(text)
    except FileNotFoundError:
        return None


def set_status(rid: str, state: str, message: str = "", filename: str | None = None) -> None:
    cur = read(rid, "status") or {}
    cur.update({"state": state, "message": message})
    if filename:
        cur["filename"] = filename
    cur.setdefault("ingested_at", datetime.now().isoformat(timespec="microseconds"))
    write(rid, "status", cur)


def list_ids() -> list[str]:
    if db.enabled():
        return [r[0] for r in db.run("select id from public.reports where status <> cast('{}' as jsonb) order by id")]
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if (p / "status.json").exists())


def iter_docs(*names: str) -> list[tuple[str, dict]]:
    """모든 보고서의 문서 여러 개를 한 번에: [(id, {이름: 내용 또는 None})]. 목록·통계·재색인용 (DB면 쿼리 한 번)."""
    for n in names:
        _check(n)
    if db.enabled():
        rows = db.run(f"select id, {', '.join(names)} from public.reports where status <> cast('{{}}' as jsonb) order by id")
        return [(r[0], {n: _val(v) for n, v in zip(names, r[1:])}) for r in rows]
    return [(rid, {n: read(rid, n) for n in names}) for rid in list_ids()]


# ---------- 원문 PDF ----------

def save_pdf(rid: str, data: bytes) -> Path:
    """로컬 작업 폴더에 쓰고, Supabase면 Storage에도 올린다."""
    p = rdir(rid) / PDF_NAME
    p.write_bytes(data)
    if db.enabled():
        from . import supa_storage

        supa_storage.upload(f"{rid}/{PDF_NAME}", data)
    return p


def local_pdf(rid: str) -> Path | None:
    """원문 PDF의 로컬 경로. Supabase면 로컬에 없을 때 Storage에서 받아 둔다 (서버 재시작·다른 인스턴스). 없으면 None."""
    p = DATA_DIR / rid / PDF_NAME
    if p.exists():
        return p
    if db.enabled():
        from . import supa_storage

        data = supa_storage.download(f"{rid}/{PDF_NAME}")
        if data is not None:
            p = rdir(rid) / PDF_NAME
            p.write_bytes(data)
            return p
    return None
