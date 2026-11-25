"""파일 기반 저장소. 해커톤용이라 DB 없이 data/<id>/ 아래 JSON으로 둔다."""
import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


def report_id(pdf_bytes: bytes) -> str:
    return hashlib.sha1(pdf_bytes).hexdigest()[:10]


def rdir(rid: str) -> Path:
    d = DATA_DIR / rid
    d.mkdir(parents=True, exist_ok=True)
    return d


def write(rid: str, name: str, obj) -> None:
    """임시 파일에 쓰고 바꿔치기한다. 처리 스레드가 쓰는 도중 화면 폴링이 반쯤 쓰인 JSON을 읽지 않도록."""
    target = rdir(rid) / f"{name}.json"
    tmp = target.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def read(rid: str, name: str):
    p = DATA_DIR / rid / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def set_status(rid: str, state: str, message: str = "", filename: str | None = None) -> None:
    cur = read(rid, "status") or {}
    cur.update({"state": state, "message": message})
    if filename:
        cur["filename"] = filename
    cur.setdefault("ingested_at", datetime.now().isoformat(timespec="microseconds"))
    write(rid, "status", cur)


def list_ids() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if (p / "status.json").exists())
