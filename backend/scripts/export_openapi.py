"""API 계약을 docs/openapi.json으로 내보낸다. app/api_models.py나 라우트를 바꾸면 꼭 실행.
사용: python scripts/export_openapi.py   (backend/ 에서)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.main import app  # noqa: E402

OUT = ROOT.parent / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"저장: {OUT}")
