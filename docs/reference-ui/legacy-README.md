# 사고사례 판단 훈련 (해커톤 프로토타입)

사조위 철도 사고조사보고서(PDF)를 올리면
1. **구조화**: 사고 경위, 직접 원인, 기여요인, 지적된 규정, 안전권고, 교육 관련 지적을 뽑아 정리하고
2. **판단 훈련**: 경위를 바탕으로 "이 상황에서 어떻게 하겠는가?" 단계별 문제를 만들고
3. **반복 패턴**: 여러 보고서에서 반복되는 규정 위반과 교육 지적을 모아 보여준다.
4. **새 사고 → 과거 사고 연결**: 새 보고서가 들어오면 비슷한 과거 사고 3건과 "이번에도 반복된 규정"을 바로 보여준다. 보고서가 늘어나면 결과도 자동으로 바뀐다(열 때마다 계산).
5. **유사사고 검색**: "야간 선로 작업 중 인접선 열차 진입"처럼 상황을 넣으면 비슷한 과거 사고와 원인·권고를 찾는다 (ChromaDB, 로컬). 원하면 검색 결과만 근거로 LLM이 요약한다.

공개된 사고조사보고서만 쓰므로 사내 데이터가 필요 없다.

## 실행 (Windows, Anaconda Prompt 기준)

```bash
cd accident-trainer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # .env 열어서 OPENAI_API_KEY, LLM_MODEL 입력
uvicorn app.main:app --reload
```
브라우저에서 http://localhost:8000 을 열고 보고서 PDF를 올린다. 1건 처리에 1~2분(LLM 호출 2번).

여러 건을 한 번에 넣으려면 `pdfs/` 폴더에 PDF를 모아 두고 `python scripts/ingest.py pdfs`를 실행한다 (중간보고서는 자동 제외).

### 새 보고서 자동 반영 (inbox 폴더)
`.env`에 `INBOX_DIR=inbox`를 넣고 서버를 켜면 `inbox/`를 5초마다 본다. 크롤러가 새 PDF를 이 폴더에 넣으면 파싱 → 구조화 → 색인 → 시나리오까지 자동으로 처리된다. 같은 내용의 파일은 다시 처리하지 않는다.

### 텍스트 없는 PDF
글자가 이미지·도형으로 들어간 보고서(샘플 50건 중 11건)는 읽기 전에 약 1초 만에 걸러서 "OCR 필요"로 표시하고 LLM을 부르지 않는다.

## 시연 순서 (예시)
1. 사람 판단이 원인인 사고 7건을 미리 넣어 둔다 (`scripts/ingest.py`).
2. 넣지 않은 1건을 화면에서 올린다 (또는 `inbox/`에 복사).
3. 처리 단계(파싱 → 구조화 → 색인 → 시나리오)가 화면에 표시되고, 끝나면 **비슷한 과거 사고 + 반복된 규정**이 바로 뜬다.
4. "공통점 요약"으로 과거 사고와의 공통 원인·권고를 근거(p.N)와 함께 보여준다.
5. "판단 훈련" 탭에서 새 사고로 만들어진 시나리오를 풀어본다.

키 없이 흐름만 확인하려면 `python -m pytest -q`를 실행한다. 가상 PDF와 가짜 LLM으로 업로드부터 시나리오까지 돌린다.

## 구조

```
app/
  parse.py     PDF -> 쪽별 텍스트([p.N]) -> 목차 기준 섹션 (경위, 조사결과, 사고원인, 안전권고 …)
  schema.py    AccidentRecord(구조화 결과), Scenario(판단 훈련) — 모든 항목에 근거 쪽 번호
  extract.py   LLM 프롬프트: 구조화 / 시나리오 생성
  watch.py     inbox 폴더 감시 (새 PDF 자동 처리)
  search.py    유사사고 검색·새 사고와 과거 사고 연결: 임베딩 -> ChromaDB(data/chroma) 색인·검색, 검색 결과 기반 요약
  llm.py       LLM 공급자 전환 (Anthropic / OpenAI / OpenAI 호환 서버 / stub)
  pipeline.py  파싱 -> 구조화 -> 시나리오, 단계별 저장
  store.py     data/<id>/*.json 파일 저장
  main.py      FastAPI
static/index.html  화면 (빌드 없음)
scripts/ingest.py  폴더 일괄 처리
tests/test_flow.py 키 없이 돌리는 흐름 테스트
```

## 파싱

`app/parse.py`의 `extract_pages()`가 쪽마다 `"[p.N]\n본문"`을 만든다.
- 쪽 아래 가운데의 숫자 줄(`12`, `- 12 -`)은 쪽번호로 보고 뺀다 (약관 파서 `pdf_lines.mark_page`와 같은 규칙).
- 선으로 그린 표는 `page.find_tables()`로 찾아 본문 글자에서 빼고, 쪽 끝에 `[표 p.N-k]` Markdown 표로 붙인다.

약관 파서(`pdfplumber-body-table-parser`)는 회사 양식 프로필·문서별 구역 설정에 묶여 있어 그대로 붙이지 않았다.
선 없는 표나 쪽을 넘어가는 표가 문제가 되면 그 파서의 `vendor/policy_rag` 표 추출을 `extract_pages()` 안에 넣으면 된다.

## 설계에서 신경 쓴 점

- **근거 표시**: 추출된 항목마다 쪽 번호와 원문 구절이 붙는다. 화면의 `p.N`을 누르면 원문 PDF의 해당 쪽이 열린다.
- **교관 검수**: 시나리오는 "검수 전" 상태로 만들어지고, 교관이 확인한 뒤 "검수 완료"로 바꾼다.
- **사내 LLM 전환**: `LLM_PROVIDER=openai` + `OPENAI_BASE_URL`로 사내 GPU의 OpenAI 호환 서버(vLLM 등)에 그대로 연결할 수 있다.

## 한계 (해커톤 범위)

- 섹션 분리는 사조위 보고서 목차 형식(1. 사실정보 / 1.1 경위 / 3.2 사고원인 / 4. 안전권고)을 가정한다. 형식이 다르면 앞부분 본문을 통째로 넣는다.
- 실제 보고서로는 아직 검증하지 않았다. 처음 몇 건은 결과를 원문과 대조해서 프롬프트를 다듬어야 한다.
- 구조화 결과는 JSON 파일, 검색 색인은 ChromaDB(`data/chroma`, 로컬 파일)에 둔다.
- 색인 단위: 개요, 경위, 직접원인, 기여요인, 규정, 안전권고, 교육지적 (구조화 항목 하나씩) + 조사결과·분석 본문 700자 조각. 보고서를 다시 처리하면 그 보고서 색인만 지우고 다시 넣는다. 임베딩 모델을 바꾸면 `data/chroma`를 지우고 `POST /api/reindex`.
