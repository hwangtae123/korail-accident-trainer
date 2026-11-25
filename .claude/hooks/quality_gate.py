"""TaskCompleted 훅: 작업을 완료로 표시하기 전에 접두어에 맞는 검사를 돌린다.

[BE] -> backend: python -m pytest -q
[FE] -> frontend: npm run build
[INT] -> 둘 다
그 외 -> 검사 없이 통과

실패하면 exit 2 + stderr로 이유를 보내서 완료를 막는다 (Claude Code hooks 규칙).
stdin으로 받는 JSON에서 task_subject를 읽는다.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 540


def run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    if cmd[0] == "npm":
        npm = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm:
            return False, "npm을 찾을 수 없음"
        cmd = [npm] + cmd[1:]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(cmd)}: {TIMEOUT}초 안에 끝나지 않음"
    out = (p.stdout + "\n" + p.stderr).strip()
    return p.returncode == 0, "\n".join(out.splitlines()[-40:])


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    subject = (data.get("task_subject") or "").strip()

    checks = []
    if subject.startswith(("[BE]", "[INT]")):
        checks.append(("backend pytest", [sys.executable, "-m", "pytest", "-q"], ROOT / "backend"))
    if subject.startswith(("[FE]", "[INT]")):
        if not (ROOT / "frontend" / "node_modules").exists():
            print("frontend/node_modules 없음 — frontend에서 npm install 먼저 실행", file=sys.stderr)
            return 2
        checks.append(("frontend build", ["npm", "run", "build"], ROOT / "frontend"))

    for name, cmd, cwd in checks:
        ok, log = run(cmd, cwd)
        if not ok:
            print(f"[quality gate] '{subject}' 완료 전 {name} 실패. 고친 뒤 다시 완료로 표시하세요.\n{log}",
                  file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
