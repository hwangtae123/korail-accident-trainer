"""파싱 전체 실행 (진입점 하나). data/의 PDF마다 단계 스크립트를 순서대로 돌리고 단계별 시간과 결과 줄을 모아 보여 준다.

  python parsing/run.py                    data/의 PDF 전부 (이미 끝난 문서는 건너뜀. 새 PDF는 구역 파일을 자동으로 만듦)
  python parsing/run.py --doc <doc_id>     이 문서만 (끝났어도 다시)
  python parsing/run.py --docs             data/의 PDF와 doc_id·구역 파일·상태 목록
  python parsing/run.py --from tree        이 단계부터 끝까지 (규칙을 고친 단계부터 다시 돌릴 때. 끝난 문서도 다시)
  python parsing/run.py --only export      이 단계만
  python parsing/run.py --force            덤프·쪽 그림·누출 해시도 처음부터 다시 (PDF가 바뀌었을 때)
  python parsing/run.py --review           확인용 출력도 만든다 (수치 리포트 results/<doc_id>/parsing/, 원문 발췌
                                           secure/<doc_id>/review/, 와이어프레임 review/<doc_id>/, 전체 Markdown과 글자 대조 export 단계)
  python parsing/run.py --skip render,leak 이 단계는 건너뜀 (백엔드에서 부를 때: 쪽 그림·누출 검사 없이)
  python parsing/run.py --list             단계 이름과 설명

문서 짝짓기 (parsing/docs.py): PDF의 sha256 (없으면 경로)이 같은 문서 설정 config/docs/<doc_id>.yaml을 쓴다. 없으면
파일 이름으로 doc_id를 만들고 문서 설정을 쓴다. 프로필은 폰트가 맞는 기존 프로필, 없으면 초안 (parsing/profile_draft.py).
구역은 덤프 다음 zones 단계 (parsing/auto_zones.py)가 쪽마다 정한다. 새 문서에 맞춰 고치는 법은 CUSTOMIZE.md.
산출물은 문서마다 secure/<doc_id>/, results/<doc_id>/, review/<doc_id>/에 나뉜다.
기본 (--review 없음)은 청킹에 필요한 결과와 그 중간 산출물만 만든다: secure/<doc_id>/tree/, tables/tables.jsonl,
boxes/, figures/ (+ 덤프·쪽 그림·박스 분석·제외 표시·영역 판정). export 단계는 건너뛴다.
단계 이름: dump, zones, render, boxes, exclude, classify, extract, box_blocks, tree, export (--review일 때만), leak.
누출 검사 해시 (secure/<doc_id>/leak_hashes.bin)가 없으면 문서마다 맨 앞에서 한 번 만든다. 한 단계라도 실패하면 그 문서는
거기서 멈추고 다음 문서로 간다. 다 끝난 문서는 results/<doc_id>/run_status.json에 sha256을 적어 다음 실행에서 건너뛴다.
화면에는 각 단계가 safeio로 낸 수치 줄만 나온다 (원문 없음). 단계의 라이브러리 출력·오류 전문은 secure/<doc_id>/logs/에 있다.
실행 (requirements.txt 환경): python parsing/run.py [옵션]
"""

import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safeio import DATA_DIR, RESULTS_ROOT, ROOT, SECURE_ROOT, Trusted, out, setup  # noqa: E402

HERE = Path(__file__).resolve().parent
# (이름, 스크립트, 설명). 순서 = 실행 순서. 뒤 단계는 앞 단계 결과를 읽는다.
STEPS = [
    ("dump", "pdf_lines.py", "PDF 쪽별 덤프 (글자·줄·영역·선)"),
    ("zones", "auto_zones.py", "자동 구역 (구역 파일이 임시일 때만, 새 PDF)"),
    ("render", "render_pages.py", "쪽 그림 (144 DPI)"),
    ("boxes", "boxes.py", "박스 라벨 열·예시 범위·쪽 넘김 이어짐"),
    ("exclude", "exclude.py", "제외 표시 (쪽번호·양식 코드·이미지·도식·일반 예시)"),
    ("classify", "tables_classify.py", "영역 판정 (제목 띠·박스·표·본문)과 표 모양"),
    ("extract", "tables_extract.py", "표 추출·쪽 넘김 이어 붙이기·확신도"),
    ("box_blocks", "box_blocks.py", "박스 블록·용어집"),
    ("tree", "tree.py", "본문 트리·표·박스·예시 그림 연결·인용·용어집 소속 조항"),
    ("export", "review/export_md.py", "전체 Markdown과 글자 대조"),
    ("leak", "leak_check.py", "누출 검사"),
]
NAMES = [s[0] for s in STEPS]


def arg_value(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def run_step(name: str, script: str, extra: list[str], doc_id: str, review: bool = False) -> tuple[int, float]:
    t0 = time.perf_counter()
    # 단계 스크립트는 PARSE_DOC로 문서를, safeio.review_mode()로 PARSE_REVIEW를 읽는다
    env = {**os.environ, "PARSE_DOC": doc_id, "PARSE_REVIEW": "1" if review else "0"}
    proc = subprocess.run([sys.executable, str(HERE / script), *extra], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)
    sec = time.perf_counter() - t0
    # 단계 스크립트의 표준 출력은 safeio.out()이 낸 줄뿐이다 (수치·라벨). 시작 줄만 빼고 그대로 보여 준다
    for line in proc.stdout.splitlines():
        if line.strip() and not line.startswith("start script="):
            out(f"  [{name}]", line=Trusted(line[:2000]))
    return proc.returncode, sec


def profile_of(d) -> str:
    import yaml

    return (yaml.safe_load(d.config.read_text(encoding="utf-8")) or {}).get("profile") or "default"


def status_path(doc_id: str) -> Path:
    return RESULTS_ROOT / doc_id / "run_status.json"


def load_status(doc_id: str) -> dict:
    p = status_path(doc_id)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def dump_source(doc_id: str) -> Path:
    """덤프를 만든 PDF의 sha256 (PDF를 바꿔 넣으면 덤프·쪽 그림을 다시 만들려고)."""
    return SECURE_ROOT / doc_id / "dump_source_sha256.txt"


def run_doc(doc_id: str, sha: str, steps: list[tuple], force: bool, review: bool) -> list[tuple[str, int, float]]:
    """한 문서의 단계를 순서대로 돌린다. 반환: (단계, rc, 초) 목록 (실패한 단계에서 멈춤)."""
    summary = []
    src = dump_source(doc_id)
    if src.exists() and src.read_text(encoding="utf-8").strip() != sha:
        force = True  # 덤프가 다른 PDF에서 나옴: 처음부터 전부
        steps = [s for s in STEPS if review or s[0] != "export"]
        out("dump_stale", action="rerun_all_steps")
    if "leak" in [s[0] for s in steps] and (force or not (SECURE_ROOT / doc_id / "leak_hashes.bin").exists()):
        rc, sec = run_step("leak_build", "leak_check.py", ["build"], doc_id)
        summary.append(("leak_build", rc, sec))
        out("step_done", name="leak_build", rc=rc, sec=round(sec, 1))
        if rc:
            return summary
    for name, script, _ in steps:
        out("step", name=name, script=script)
        extra = ["--force"] if force and name in ("dump", "render") else []
        rc, sec = run_step(name, script, extra, doc_id, review)
        summary.append((name, rc, sec))
        out("step_done", name=name, rc=rc, sec=round(sec, 1))
        if rc:
            out("stopped", at=name, rc=rc, log=Trusted(f"secure/{doc_id}/logs/ (이 단계의 오류 전문)"))
            break
        if name == "dump":
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(sha + "\n", encoding="utf-8")
    return summary


def main() -> int:
    setup("run", shared=True)
    if "--list" in sys.argv:
        for name, script, desc in STEPS:
            out("step", name=name, script=script, about=Trusted(desc))
        return 0
    from docs import discover

    start, only, want = arg_value("--from"), arg_value("--only"), arg_value("--doc") or os.environ.get("PARSE_DOC")
    for v in (start, only):
        if v is not None and v not in NAMES:
            out("error", unknown_step=v, steps=NAMES)
            return 2
    docs = discover()
    if not docs:
        out("error", reason="no_pdf_in_data", data_dir=Trusted(str(DATA_DIR)))
        return 2
    if "--docs" in sys.argv:
        for d in docs:
            st = load_status(d.doc_id)
            out("doc", doc_id=Trusted(d.doc_id), pdf=Trusted(d.pdf.name), config=Trusted(d.config.relative_to(ROOT).as_posix()),
                profile=Trusted(profile_of(d)), match=d.status, done=st.get("sha256") == d.sha256 and bool(st.get("ok")))
        return 0
    if want:
        docs = [d for d in docs if d.doc_id == want and d.status != "duplicate"]
        if not docs:
            out("error", reason="doc_not_found_in_data", doc_id=Trusted(want))
            return 2
    review = "--review" in sys.argv
    full_steps = [s for s in STEPS if review or s[0] != "export"]  # 전체 Markdown·글자 대조는 확인용
    if only:
        steps = [s for s in STEPS if s[0] == only]
    else:
        steps = [s for s in full_steps if NAMES.index(s[0]) >= NAMES.index(start)] if start else full_steps
    skip = set((arg_value("--skip") or "").split(",")) - {""}
    if skip - set(NAMES):
        out("error", unknown_skip=sorted(skip - set(NAMES)), steps=NAMES)
        return 2
    steps = [s for s in steps if s[0] not in skip]
    full_steps = [s for s in full_steps if s[0] not in skip]
    force = "--force" in sys.argv
    rerun = bool(force or start or only or want or review)
    out("mode", review=review, docs=len(docs))

    results = []
    for d in docs:
        did = Trusted(d.doc_id)
        if d.status == "duplicate":
            out("doc_skip", doc_id=did, reason="same_pdf_already_in_data", pdf=Trusted(d.pdf.name))
            continue
        if d.status == "conflict":
            out("doc_skip", doc_id=did, reason="pdf_changed_but_zones_checked_by_hand",
                config=Trusted(d.config.relative_to(ROOT).as_posix()))
            results.append((d.doc_id, "conflict", 0.0))
            continue
        st = load_status(d.doc_id)
        if not rerun and d.status == "matched" and st.get("sha256") == d.sha256 and st.get("ok"):
            out("doc_skip", doc_id=did, reason="up_to_date")
            results.append((d.doc_id, "skip", 0.0))
            continue
        doc_steps = full_steps if d.status in ("new", "changed") else steps  # 새 PDF는 덤프부터 해야 한다
        out("doc", doc_id=did, pdf=Trusted(d.pdf.name), match=d.status, profile=Trusted(profile_of(d)),
            profile_source=d.profile_note or None, steps=[s[0] for s in doc_steps])
        if d.profile_note == "drafted":
            out("note", msg=Trusted(f"프로필 초안 config/profiles/{d.doc_id}.yaml 을 확인하세요 (CUSTOMIZE.md)"))
        summary = run_doc(d.doc_id, d.sha256, doc_steps, force or d.status == "changed", review)
        ok = all(rc == 0 for _, rc, _ in summary)
        out("doc_summary", doc_id=did, steps=[f"{n}:{'ok' if rc == 0 else 'FAIL'}:{sec:.1f}s" for n, rc, sec in summary],
            total_sec=round(sum(s for _, _, s in summary), 1))
        p = status_path(d.doc_id)
        ran_all = [n for n, _, _ in summary if n != "leak_build"] == [s[0] for s in full_steps]
        if ok and (ran_all or st.get("sha256") == d.sha256):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"doc_id": d.doc_id, "pdf": d.pdf.name, "sha256": d.sha256, "ok": True,
                                     "finished": datetime.datetime.now().isoformat(timespec="seconds"),
                                     "steps": [n for n, _, _ in summary]}, ensure_ascii=False, indent=1), encoding="utf-8")
        elif not ok and p.exists():
            p.unlink()
        results.append((d.doc_id, "ok" if ok else "FAIL", sum(s for _, _, s in summary)))
    out("summary", docs=[Trusted(f"{i}:{r}:{t:.0f}s") for i, r, t in results],
        failed=sum(r in ("FAIL", "conflict") for _, r, _ in results))
    return 1 if any(r in ("FAIL", "conflict") for _, r, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
