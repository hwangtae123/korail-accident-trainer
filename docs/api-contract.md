# API 계약 설명

정확한 형식은 `docs/openapi.json`(자동 생성)이 기준이다. 이 문서는 동작 규칙을 설명한다.
서버를 띄우면 http://localhost:8000/docs 에서 직접 호출해 볼 수 있다.

## 처리 상태 (`ReportStatus.state`)

```
queued -> parsing -> extracting -> indexing -> scenario -> done
                 \-> ocr_needed   (텍스트 레이어 없는 PDF. LLM을 부르지 않고 멈춤)
         (어느 단계든) -> error   (message에 이유)
```
- 업로드 직후 `queued`. 1건 처리에 LLM 호출 2번, 보통 1~2분.
- 프론트는 `queued`~`scenario`이면 3초마다 `GET /api/reports/{id}`를 다시 부른다.
- `extracting` 이후에는 `record`가 생기므로 사고 정보를 먼저 보여줄 수 있다. 시나리오는 `done` 이후.
- 서버가 처리 중에 꺼지면 다음 시작 때 해당 건을 `error`(다시 올려 달라는 메시지)로 바꾼다.

## 엔드포인트

| 메서드 | 경로 | 설명 | 상태 |
|---|---|---|---|
| GET | `/api/health` | 연결 확인 | 구현 |
| POST | `/api/reports` | PDF 업로드(multipart `file`). 같은 파일이면 `new:false`로 재처리 안 함 | 구현 |
| GET | `/api/reports` | 목록. 새로 접수된 순 | 구현 |
| GET | `/api/reports/{id}` | 상태 + 구조화 결과(`record`, 처리 전 null) | 구현 |
| GET | `/api/reports/{id}/pdf` | 원문 PDF. 근거 쪽은 `#page=N` 붙여서 열기 | 구현 |
| GET | `/api/reports/{id}/related` | 비슷한 과거 사고 3건 + `shared_rules`(반복된 규정). 열 때마다 계산 | 구현 |
| POST | `/api/reports/{id}/compare` | 과거 사고와 공통점 LLM 요약 (검색 결과만 근거) | 구현 |
| GET | `/api/reports/{id}/scenario` | 판단 훈련 시나리오 | 구현 |
| PUT | `/api/reports/{id}/scenario` | 교관이 고친 시나리오 저장 | **501 (BE-2)** |
| POST | `/api/reports/{id}/scenario/regenerate` | 시나리오 다시 생성 (상태가 queued로 돌아감) | 구현 |
| POST | `/api/reports/{id}/scenario/review` | 검수 완료 표시 | 구현 |
| GET | `/api/stats` | 반복 패턴: 사고유형·지적 규정 집계, 교육 관련 지적 목록 | 구현 |
| POST | `/api/search` | `{q}` 상황 설명 → 비슷한 사고 (LLM 없이) | 구현 |
| POST | `/api/ask` | `{q}` 검색 결과로 LLM 요약 | 구현 |
| POST | `/api/briefing` | `{work}` 작업 전 안전 브리핑(TBM) | **501 (BE-3)** |
| POST | `/api/reindex` | 검색 색인 다시 만들기 (임베딩 모델 바꿨을 때) | 구현 |

## 근거(`Evidence`)

모든 추출 항목에 붙는다: `page`(원문 쪽 번호, PDF 기준 1부터), `quote`(원문 구절 40자 이내), `verified`.
- `verified`: `quote`가 그 쪽 원문에 실제로 있는지 코드로 대조한 결과. `true` 확인됨 / `false` 원문에서 못 찾음 / `null` 아직 확인 안 함(BE-1 전까지 항상 null).

## 오류

- `400` PDF가 아님 · `404` 없는 보고서 또는 아직 없는 결과(예: 처리 전 scenario) · `422` 요청 형식 오류 · `501` 아직 구현 전
- LLM 실패는 HTTP 오류가 아니라 처리 상태 `error` + message로 나타난다.
