# 배포

## 지금 방식: Vercel 프로젝트 하나 + Supabase (https://korail-accident-trainer.vercel.app)

| 무엇 | 어디 | 내용 |
|---|---|---|
| 화면 | Vercel 정적 파일 | `frontend/` 빌드 (`vercel.json`의 buildCommand) |
| API | Vercel Python 함수 `api/index.py` (최대 300초) | `backend/app`의 FastAPI 앱 + 레이아웃 파서(`parser/`, 서브프로세스) |
| 데이터 | Supabase | DB(`reports`), 검색 벡터(pgvector `report_chunks`), 원문 PDF(Storage `reports` 버킷) |

서버리스라서 달라지는 점
- **업로드**: 함수는 약 4.5MB가 넘는 요청을 받지 못한다(158건 중 51건이 넘음, 최대 32MB). 화면이 PDF의 SHA-1로 id를 만들고
  `POST /api/reports/upload-url`로 받은 서명 주소에 PDF를 직접 PUT한 뒤 `POST /api/reports/{id}/process`를 부른다.
  서버는 Storage에서 PDF를 다시 받아 PDF인지, 내용 해시가 id와 같은지 확인한 뒤 처리한다.
- **처리**: `PROCESS_IN_REQUEST=1`(api/index.py)이면 처리 요청 안에서 끝까지 한다 (보고서 1건 약 1~2분).
  화면은 그 응답을 기다리지 않고 3초마다 상태를 본다. 함수가 시간 제한으로 죽어 '처리 중'에 330초 넘게 머문 건은 읽을 때 `error`로 바뀐다.
- 쓸 수 있는 디스크는 `/tmp`뿐이라 `DATA_DIR=/tmp/accident-trainer` (PDF 사본·파서 작업 폴더, 지워져도 됨).

배포: 저장소 루트에서 `vercel deploy --prod` (CLI 로그인·`vercel link` 필요).
Vercel 환경변수(Production): `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`(이상 Sensitive),
`LLM_PROVIDER`, `LLM_MODEL`, `EMBED_PROVIDER`, `EMBED_MODEL`. `VITE_API_BASE`·`CORS_*`는 같은 주소라 필요 없다.

아래 2~4번(Docker 컨테이너 + 화면 따로)은 Vercel 대신 서버를 직접 돌릴 때의 방법이다.

## 1. Supabase 프로젝트
1. 프로젝트를 만들고 대시보드에서 세 값을 복사해 `accident-trainer/.env`에 넣는다 (채팅·깃에 올리지 않음)
   - `DATABASE_URL`: Connect > **Session pooler** 연결 문자열 (비밀번호 채워서)
   - `SUPABASE_URL`: Project Settings > API > Project URL
   - `SUPABASE_SERVICE_ROLE_KEY`: Project Settings > API > service_role 키
2. 테이블·pgvector·비공개 버킷 만들기 (둘 중 하나)
   - Supabase CLI(로그인·`supabase link`된 폴더에서): `supabase db query --linked --yes -f backend/supabase/schema.sql`
   - `backend/`에서 `python scripts/init_db.py`
   - 또는 `backend/supabase/schema.sql`을 SQL Editor에 붙여 넣고 실행
3. (권장) 앱 전용 역할: `backend/supabase/app_role.sql`의 `:'app_password'`를 새 비밀번호로 바꿔 실행하고,
   `DATABASE_URL`을 `postgresql://accident_trainer.<ref>:<비밀번호>@<pooler 호스트>:5432/postgres`로 둔다.
   postgres(관리자) 비밀번호 없이 reports·report_chunks만 읽고 쓰는 최소 권한 접속이다.
4. 연동 시험: `TEST_DATABASE_URL`을 `DATABASE_URL`과 같은 값으로 주고 `python -m pytest -q tests/test_supabase.py`

## 2. 로컬에서 처리해 둔 보고서 옮기기 (선택)
`backend/`에서 `python scripts/migrate_to_supabase.py`
- `backend/data/`의 보고서(문서 4개 + PDF)와 검색 임베딩을 그대로 옮긴다. LLM·임베딩 비용 없음.
- 임베딩 모델을 바꿨으면 `--reindex`.

## 3. 서버 컨테이너
저장소 루트의 `Dockerfile`로 빌드한다. 호스팅 서비스의 환경변수에 넣을 값:

| 변수 | 값 |
|---|---|
| `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | 위 1번 |
| `LLM_PROVIDER`, `OPENAI_API_KEY`, `LLM_MODEL` | `.env`와 같게 (예: openai, gpt-6-luna) |
| `EMBED_PROVIDER`, `EMBED_MODEL` | `openai`, `text-embedding-3-small` |
| `CORS_ORIGINS`, `CORS_ORIGIN_REGEX` | Vercel 화면 주소 (아래 4번) |
| `PORT` | 보통 호스팅이 자동으로 준다 (없으면 8000) |

- 상태 확인 경로: `/api/health`. API는 `/api/…`.
- 컨테이너의 `DATA_DIR`(/tmp)은 PDF 캐시·파서 작업 폴더일 뿐이라 지워져도 된다. 데이터는 모두 Supabase에 있다.
- 로컬에서 시험: `docker build -t accident-trainer .` 후 `docker run -p 8000:8000 --env-file .env accident-trainer`

## 4. 화면 (Vercel)
1. Vercel에서 이 저장소를 가져오고 **Root Directory를 `frontend`**로 둔다 (`frontend/vercel.json`이 Vite 빌드 설정을 담고 있다).
2. Vercel 환경변수 `VITE_API_BASE` = 백엔드 주소 (예: `https://accident-trainer-api.onrender.com`, 끝에 `/` 없이).
   빌드할 때 들어가므로 바꾸면 다시 배포해야 한다.
3. 백엔드 환경변수에 Vercel 주소를 허용한다:
   - `CORS_ORIGINS` = `https://<프로젝트>.vercel.app` (정식 주소, 쉼표로 여러 개)
   - `CORS_ORIGIN_REGEX` = `https://<프로젝트>(-[a-z0-9-]+)?\.vercel\.app` (미리보기 배포 주소까지)
4. 확인: Vercel 주소에서 보고서 목록이 뜨고, 브라우저 개발자 도구 Network에 `…/api/reports`가 200이면 된다.
   CORS 오류가 나면 3번 주소가 정확한지(https, 끝 `/` 없음) 본다.

로컬에서 이 구성을 흉내 내려면: 백엔드를 `CORS_ORIGINS=http://localhost:4173`으로 띄우고,
`frontend/`에서 `VITE_API_BASE=http://localhost:8000`으로 `npm run build` 후 `npx vite preview --port 4173`.

백엔드 컨테이너도 `/`에서 화면을 내보내지만(같은 주소라 CORS 불필요), Vercel을 쓰면 그쪽은 쓰지 않아도 된다.

## 주의
- 처리는 서버 안 백그라운드 작업이다. 처리 중에 컨테이너가 재시작되면 그 보고서는 `error`(다시 올려 달라는 메시지)가 된다.
- 인스턴스는 1개로 둔다 (여러 개면 같은 보고서를 동시에 처리할 수 있다).
- 화면에 로그인이 없다. 주소를 아는 사람은 누구나 보고서를 올리고 LLM을 부를 수 있으니, 공개 주소로 둘 때는 접근 제한을 먼저 정한다.
