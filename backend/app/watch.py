"""inbox 폴더 감시: 새 PDF가 들어오면 자동으로 처리한다 (크롤러가 새 보고서를 떨어뜨리는 자리).

INBOX_DIR 환경변수를 주면 서버가 켜질 때 같이 돈다. 이미 처리한 파일(같은 내용)은 건너뛴다.
"""
import os
import threading
import time
from pathlib import Path

from .pipeline import ingest_bytes, process

POLL_SEC = 5


def _loop(inbox: Path, stop: threading.Event) -> None:
    seen: dict[str, float] = {}
    while not stop.is_set():
        for pdf in sorted(inbox.glob("*.pdf")):
            mtime = pdf.stat().st_mtime
            if seen.get(pdf.name) == mtime:
                continue
            # 복사 중인 파일을 읽지 않도록 크기가 안정될 때까지 한 번 기다린다
            size = pdf.stat().st_size
            time.sleep(1)
            if pdf.stat().st_size != size:
                continue
            seen[pdf.name] = mtime
            rid, is_new = ingest_bytes(pdf.read_bytes(), pdf.name)
            if is_new:
                print(f"[inbox] 새 보고서: {pdf.name} -> {rid}", flush=True)
                process(rid)  # 한 건씩 차례로 처리
        stop.wait(POLL_SEC)


def start(inbox_dir: str) -> threading.Event:
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    threading.Thread(target=_loop, args=(inbox, stop), daemon=True, name="inbox-watch").start()
    print(f"[inbox] 감시 시작: {inbox.resolve()}", flush=True)
    return stop
