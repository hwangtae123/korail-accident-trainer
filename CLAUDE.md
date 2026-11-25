# 사고사례 판단 훈련 (accident-trainer)

항공·철도사고조사위원회의 철도 사고조사보고서(PDF)를 구조화해서
① 사고 정보 카드(근거 쪽 번호 포함) ② 단계별 판단 훈련 시나리오 ③ 비슷한 과거 사고 연결 ④ 유사사고 검색을 제공한다.
타겟 사용자는 코레일 인재개발원 기술교육센터 교관과 교육생이다. 해커톤 프로토타입이다.

## 구조와 담당 (파일 소유권 — 남의 영역은 수정하지 않는다)

| 경로 | 담당 | 내용 |
|---|---|---|
| `backend/` | backend-dev | FastAPI, 파싱(레이아웃 파서 호출), LLM 추출, 검색(pgvector / 로컬 numpy), 저장(Supabase / 로컬 파일), pytest |
| `parser/` | 리드 (고칠 때 리드에게 먼저 알림) | 레이아웃 파서: 보고서 PDF → 장·절 제목 트리·표·각주. 백엔드는 `backend/app/layout_parser.py`로 부른다 (실패하면 처리 상태 error + 이유. 다른 파서로 넘어가지 않음). 고치는 법 `parser/CUSTOMIZE.md` |
| `frontend/` | frontend-dev | React + Vite + TypeScript |
| `docs/openapi.json` | backend-dev가 스크립트로만 생성 | API 계약 (손으로 고치지 않음) |
| `docs/api-contract.md`, `docs/backlog.md`, `docs/ui-spec.md`, `CLAUDE.md` | 리드 | 계약 설명, 작업 목록, 화면 명세 |
| `docs/reference-ui/` | 읽기 전용 | 이전 버전 화면(HTML 한 장). 동작 참고용 |

## 명령어

백엔드 (`backend/`에서):
- 설치: `pip install -r requirements.txt` (Python 3.10+)
- 테스트: `python -m pytest -q` — API 키 없이 가짜 LLM·임베딩으로 돈다
- 개발용 가짜 데이터: `python scripts/seed_dev.py` (제목에 "테스트용 가상 보고서", 실제 사고 아님)
- 서버: `uvicorn app.main:app --reload --port 8000` (키 없이 돌릴 땐 환경변수 `EMBED_PROVIDER=stub`)
- 계약 내보내기: `python scripts/export_openapi.py` → `docs/openapi.json`
- 저장소: `.env`에 `DATABASE_URL`이 있으면 Supabase(PostgreSQL + pgvector + Storage), 없으면 로컬 파일(`backend/data/`). 테스트는 항상 로컬 파일. 배포 방법 `docs/deploy-supabase.md`
- 파싱: `parse_report`가 레이아웃 파서(`../parser`)를 서브프로세스로 돌린다 (보고서 한 건 20~70초). 파서 위치 `PARSER_DIR`, 시간 제한 `LAYOUT_PARSER_TIMEOUT`(초)

파서 (`parser/`에서, 백엔드와 같은 가상환경):
- 일괄 파싱: `python parsing/run.py` → `../../data`의 PDF를 `../parsed/`로 (폴더는 `config/paths.yaml`). 처음 돌릴 때 PDF마다 `config/docs/<doc_id>.yaml`이 생긴다

프론트 (`frontend/`에서):
- 설치: `npm install` (Node ^20.19 또는 >=22.12)
- 개발 서버: `npm run dev` → http://localhost:5173 (`/api`는 8000으로 프록시)
- 타입 생성: `npm run gen:api` → `src/api/schema.d.ts` (손으로 고치지 않음)
- 검사·빌드: `npm run build` (tsc + vite)

## API 계약 규칙

1. 계약의 원본은 `backend/app/api_models.py`(+ 라우트)이고, `docs/openapi.json`은 그 결과물이다.
2. **계약을 바꾸기 전에 리드에게 메시지로 알리고 승인받는다.** 승인 후 backend-dev가 `export_openapi.py`를 실행하고 frontend-dev에게 "gen:api 다시 실행"을 알린다.
3. `backend/tests/test_contract.py`가 서버와 `docs/openapi.json`이 다르면 실패한다.
4. 아직 구현 안 된 엔드포인트는 `501`을 돌려준다. 프론트는 501이면 "준비 중"을 보여주고 깨지지 않아야 한다.

## 작업(Task) 이름 규칙

- `[BE] ...` 백엔드, `[FE] ...` 프론트, `[INT] ...` 통합 확인. backlog ID를 붙인다: `[BE] BE-2 시나리오 저장 API`
- 작업을 완료로 표시하면 `.claude/hooks/quality_gate.py`가 접두어에 맞는 검사(pytest / npm run build)를 돌리고, 실패하면 완료를 막는다.

## 지켜야 할 것

- **근거 없는 내용을 만들지 않는다.** 화면·LLM 출력의 모든 사고 정보에는 근거 쪽(`p.N`)이 붙고, LLM이 쓴 문장에는 "원문과 대조하세요" 안내를 붙인다.
- 테스트·개발 데이터는 가짜임을 제목에 표시한다. 실제 사고처럼 보이는 가짜 데이터를 만들지 않는다.
- 기술 용어는 영어 그대로(FastAPI, ChromaDB, REST API…), 화면 문구는 한국어.
- `.env`, API 키, `backend/data/`는 커밋하지 않는다.
- 완료 기준: 해당 backlog 항목의 수용 기준 충족 + 테스트/빌드 통과 + 리드에게 무엇을 바꿨는지 한 줄 보고.
