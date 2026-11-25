"""API 계약(docs/openapi.json)과 실제 서버가 어긋나지 않았는지 확인.
실패하면: python scripts/export_openapi.py 로 다시 내보내고, 프론트에서 npm run gen:api.
(계약 변경은 팀 리드 합의 후에만 — CLAUDE.md)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_openapi_matches_export():
    from scripts.export_openapi import OUT, render

    assert OUT.exists(), "docs/openapi.json 없음 — python scripts/export_openapi.py"
    assert json.loads(OUT.read_text(encoding="utf-8")) == json.loads(render()), \
        "API가 docs/openapi.json과 다름 — export_openapi.py 실행 후 프론트 gen:api"
