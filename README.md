# 사고사례 판단 훈련 — agent teams 키트

사조위 철도 사고조사보고서 → 구조화(근거 쪽 번호) → 판단 훈련 시나리오 → 비슷한 과거 사고 연결.
백엔드는 동작하는 상태이고, 프론트(React + Vite + TS)는 연결만 된 뼈대다. 남은 일을 Claude Code agent teams로 나눠 구현한다.

- 시작하기: **docs/team-kickoff.md** (설치, 리드 프롬프트, 조작법)
- 팀 규칙: CLAUDE.md (모든 팀원이 자동으로 읽음)
- 할 일: docs/backlog.md · 계약: docs/api-contract.md + docs/openapi.json · 화면: docs/ui-spec.md
- 역할 정의: .claude/agents/ (backend-dev, frontend-dev, qa-reviewer)
- 품질 게이트: .claude/hooks/quality_gate.py — `[BE]`/`[FE]` 작업을 완료로 표시할 때 pytest / npm run build

```
backend/    FastAPI + pdfplumber + LLM(OpenAI/Anthropic) + ChromaDB   (python -m pytest -q)
frontend/   React 19 + Vite 8 + TypeScript + openapi-fetch          (npm run build)
parser/     레이아웃 파서 (보고서 PDF → 장·절 트리·표·각주, 백엔드 parse_report가 씀)   (python parsing/run.py)
docs/       계약·명세·작업 목록, reference-ui/ (이전 HTML 화면)
```

실제 보고서로 돌리려면 `backend/.env.example`을 `.env`로 복사해 `OPENAI_API_KEY`, `LLM_MODEL`을 채운다.

배포(Supabase + 백엔드 Docker 컨테이너 + Vercel 화면): **docs/deploy-supabase.md**
