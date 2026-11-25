# Agent teams로 돌리기 (Windows, Claude Code)

## 0. 준비 (한 번만)
- Claude Code (agent teams는 실험 기능. 이 레포의 `.claude/settings.json`이 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`을 켠다)
- Python 3.10+, Node ^20.19 또는 >=22.12, Git for Windows(Git Bash: 품질 게이트 훅이 bash로 돈다)
- 분할 화면은 Windows Terminal·VS Code 터미널에서 지원되지 않는다. 기본값인 **in-process 모드**로 쓴다.

```bash
cd accident-trainer
git init && git add -A && git commit -m "kit"     # 팀이 바꾼 걸 diff·되돌리기 위해 권장

cd backend
pip install -r requirements.txt
python -m pytest -q                 # 5 passed 나오면 OK
python scripts/seed_dev.py          # 프론트 개발용 가짜 데이터 2건
cd ../frontend
npm install
npm run build                       # 통과하면 OK
cd ..
claude                              # 레포 루트에서 실행 (이 세션이 리드가 된다)
```

처음 열면 이 폴더를 신뢰할지 묻는다. 신뢰해야 `.claude/agents/`의 역할 정의와 훅이 적용된다.

## 1. 리드에게 붙여 넣을 프롬프트

```text
CLAUDE.md, docs/backlog.md, docs/api-contract.md, docs/ui-spec.md를 읽고 agent team을 만들어줘.

팀원 3명 (각자 이 레포의 subagent 정의를 agent type으로 써서 spawn):
- 이름 "be": backend-dev agent type
- 이름 "fe": frontend-dev agent type
- 이름 "qa": qa-reviewer agent type

할 일:
1. docs/backlog.md의 항목으로 Task를 만들어. 제목은 "[BE] BE-1 근거 자동 확인"처럼 접두어+ID. FE-4는 BE-2에, FE-6은 BE-3에 의존하게 걸되, 화면 작업은 먼저 시작해도 된다고 설명에 적어.
2. be는 [BE], fe는 [FE] 작업을 자기가 가져가서 진행. qa는 작업이 완료될 때마다 점검하고 문제를 담당자에게 알림.
3. 너(리드)는 직접 구현하지 말고 조율만 해. API 계약(app/api_models.py) 변경 요청이 오면 영향을 보고 승인/거절해.
4. 파일 소유권: be는 backend/만, fe는 frontend/만 수정. 둘이 같은 파일을 고치지 않게 해.
5. 모든 [BE]/[FE]가 끝나면 qa에게 INT-1을 맡기고, 결과를 나에게 요약해줘.
팀원이 끝날 때까지 기다리고, 중간에 막히면 나에게 물어봐.
```

선택: 위험한 작업을 계획부터 보고 싶으면, 리드를 plan mode로 바꾼 뒤(Shift+Tab) 위 프롬프트를 보내면 팀원이 계획을 먼저 세우고 승인 후 구현한다.

## 2. 진행 중 조작 (in-process 모드)
- 프롬프트 아래 agent 패널에서 ↑↓로 팀원 선택, Enter로 그 팀원 대화 보기·직접 메시지, Esc로 해제
- Ctrl+T: 공유 작업 목록 보기 / 선택한 팀원에서 `x`: 중지
- 팀원 권한 요청은 리드 화면에 뜬다. 자주 쓰는 명령(pytest, npm run build 등)은 `.claude/settings.json`에 미리 허용해 뒀다.

## 3. 자주 생기는 일
- **리드가 직접 코딩을 시작함** → "Wait for your teammates to complete their tasks before proceeding"
- **작업이 완료 안 됨으로 멈춤** → 품질 게이트가 막은 것일 수 있다. 해당 팀원 대화에서 실패 로그 확인. 실제로 끝났는데 상태만 안 바뀐 경우 리드에게 상태를 고치라고 말한다.
- **팀원이 subagent로만 뜸** → "agent team으로, teammate로 spawn해줘"라고 다시 요청.
- **세션을 /resume 하면 팀원이 사라짐** → 실험 기능 한계. "팀원을 다시 spawn해줘".
- **토큰 사용량** → 팀원마다 별도 세션이라 혼자 할 때보다 훨씬 많이 쓴다. 역할 정의의 `model: sonnet`을 바꾸면 팀원 모델이 바뀐다.

## 4. 끝난 뒤 확인
```bash
cd backend && python -m pytest -q && cd ../frontend && npm run build
# 실행: 터미널 1) backend: uvicorn app.main:app --reload --port 8000   (키 없으면 EMBED_PROVIDER=stub)
#       터미널 2) frontend: npm run dev  -> http://localhost:5173
git diff --stat                     # 팀이 바꾼 파일
```
