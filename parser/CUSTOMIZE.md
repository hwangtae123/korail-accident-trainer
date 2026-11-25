# 새 문서에 맞추기

이 저장소는 보험 약관 한 권으로 규칙을 맞췄다. 다른 문서는 **넣고 → 돌리고 → 화면 수치를 보고 → 설정을 고치고 → 다시 돌린다**.
대부분은 설정 파일 두 개 (문서 설정, 프로필)로 끝나고, 번호 모양이 아예 다른 문서만 코드를 고친다.

| 고칠 곳 | 파일 | 범위 |
|---|---|---|
| 문서 설정 | `config/docs/<doc_id>.yaml` | 문서 하나: PDF, 쓸 프로필, 구역 (쪽 범위), 이 문서만의 임계값 |
| 양식 프로필 | `config/profiles/<이름>.yaml` | 같은 양식 (같은 회사·같은 템플릿) 문서 모두: 폰트 역할, 박스 라벨, 참조 규칙 |
| 공통 임계값 | `config/params.yaml` | 모든 문서. 보통은 고치지 않고 문서 설정 `params`로 덮어쓴다 |
| 코드 | `parsing/` | 번호 모양·문서 구조가 조문형이 아닐 때 (아래 "코드를 고쳐야 하는 경우") |

## 1. 넣고 돌리기

```bash
cp ~/받은문서.pdf data/
$PY parsing/run.py --docs      # doc_id와 쓸 프로필 확인 (새 문서면 이때 문서 설정·프로필 초안이 생김)
$PY parsing/run.py             # 새 문서만 파싱
```

새 문서가 들어오면 자동으로:
- 문서 설정 `config/docs/<doc_id>.yaml`을 만든다 (`doc_id`는 파일 이름에서).
- 프로필: 본문 폰트와 조 제목 폰트가 맞는 기존 프로필이 있으면 그것 (`profile_source=reused`),
  없으면 폰트 분포로 초안 `config/profiles/<doc_id>.yaml`을 만든다 (`profile_source=drafted`).
- 구역: 덤프 뒤 `zones` 단계가 앞쪽 표지·목차·간지를 빼고 나머지를 포함으로 둔다 (`zones_status: auto`).

## 2. 화면 수치 보기

원문은 화면에 나오지 않는다. 다음 줄을 본다.

| 줄 | 볼 것 | 이상하면 |
|---|---|---|
| `[dump] profile_warn code=body_font_mismatch` | 프로필 body 폰트가 실제 가장 많은 폰트와 다름 | 프로필 `fonts.body` (3단계) |
| `[dump] profile_warn code=profile_font_unused:<역할>` | 프로필의 그 폰트가 문서에 없음 | 그 역할 폰트 (3단계) |
| `[zones] zone pages=… included=…` | 포함 쪽 범위 | 문서 설정 `zones` (4단계) |
| `[zones] warn reason=no_included_pages_detected…` | 편·관·조 제목을 못 찾아 전체 쪽을 포함함 | 프로필 제목 폰트 (3단계) 또는 조문형이 아닌 문서 (6단계) |
| `[tree] done types={…}` | `article` (조), `gwan`, `contract` 수가 문서와 맞는지 | 조 0개 = 조 제목 폰트 틀림 |
| `[tree] done checks={…}` | `content_outside_article` (조 밖 내용), `item_number_jump` (번호 건너뜀), `article_not_increasing` | 아래 표 |
| `[extract] done low=…` | 확신도 낮은 표 수 | `--review`로 표 확인 |
| `[leak] result=PASS` | 원문 누출 없음 | FAIL이면 그 파일에서 원문을 뺀다 |

`checks`가 많을 때:
- `content_outside_article`가 많음: 조 제목 줄을 못 알아봄 (프로필 `article_title`) 또는 조 앞 안내문이 포함 구역에 들어감 (구역).
- `item_number_jump`가 많음: 들여쓰기 허용 폭 (`tree.item_align_tol_pt`)이 문서와 안 맞음 → 문서 설정 `params`로 조정.
- `text_directly_under_contract`·`…_gwan`: 제목 다음 줄이 제목 둘째 줄로 붙지 않음 (`tree.title_cont_gap_ratio`).

사람이 원문으로 확인하려면 `$PY parsing/run.py --doc <doc_id> --review`:
`results/<doc_id>/parsing/export_md_report.md` (원본 대비 빠진 글자 수), `tree_report.md` (수치),
`secure/<doc_id>/review/full_parse.md` (파싱 결과 전체를 읽기 순서로. 사람만 본다).

## 3. 프로필 고치기 (`config/profiles/<이름>.yaml`)

초안 맨 위 주석에 폰트 분포 표가 있다 (폰트 키, 글자 수, 줄 수, 줄 맨 앞이 제N편·제N관·제N조인 줄 수).
다시 보려면 `$PY parsing/profile_draft.py --doc <doc_id>`. 폰트 키는 `<폰트 이름>/<크기>` (예: `SLIB/10`).

| 역할 | 뜻 | 정하는 법 |
|---|---|---|
| `fonts.body` | 본문 | 글자 수가 가장 많은 폰트 |
| `fonts.article_title` | 조 제목 (`제N조`) | `article=` 수가 많은 폰트. 본문 속 "제N조에 따라"와 구별하는 기준이라 본문 폰트와 달라야 좋다 |
| `fonts.gwan_title`, `pyeon_title` | 관·편 제목 | `gwan=`, `pyeon=` 수가 많은 폰트. 없으면 `UNSET/0` |
| `fonts.title_band` | 약관명·특약명 (계약 단위 제목). 목록 | 크고 줄 수가 적은 폰트. 이 폰트 줄마다 `contract` 노드가 생긴다. 표지 제목 폰트는 빼도 된다 |
| `fonts.section_title` | 별표·부록 제목 (번호 패턴 없는 큰 제목) | 없으면 `UNSET/0` |
| `fonts.small` | 작은 글씨 (보험 문서의 장해분류표 판별에만 씀) | 보통 `UNSET/0` |
| `fonts.form_code` + `form_code_regex` | 쪽 위 양식 코드 줄 (제외됨) | 쪽마다 붙은 관리 번호가 있으면 그 폰트와 정규식 |
| `bold_font_prefixes` | 굵은 폰트 이름 앞부분 (이름에 `Bold`가 있으면 따로 안 적어도 됨) | 조 제목 폰트 이름 |
| `box_labels` | 테두리 상자 왼쪽 라벨 글자 → 박스 종류 | 문서의 설명·유의사항 상자 라벨 글자 |
| `example` | 예시 시작 줄 (`<예시>`) 규칙 | |
| `references` | 다른 약관·법령 참조를 가르는 낱말 | |
| `auto_zones` | `insurance` (주계약·특약 구역 이름) / `generic` | 보험 약관이 아니면 `generic` |

같은 양식의 다른 문서는 문서 설정의 `profile:`에 같은 이름을 적는다 (새 PDF는 폰트가 맞으면 자동으로 고른다).
프로필을 고쳤으면 `$PY parsing/run.py --doc <doc_id>`. 덤프도 굵기 판정과 박스 라벨 찾기에 프로필을 쓰므로
`bold_font_prefixes`·`box_labels`를 고쳤으면 `--force`를 붙여 덤프부터 다시 한다.

## 4. 문서 설정 고치기 (`config/docs/<doc_id>.yaml`)

```yaml
doc_id: 보험_약관_2026
pdf: data/보험 약관(2026).pdf
sha256: …                     # 자동. PDF를 바꾸면 달라진다
pages: 120
profile: default              # config/profiles/default.yaml
params: {tree: {item_align_tol_pt: 5}}   # 이 문서만 config/params.yaml을 덮어씀 (빈 값이면 {})
zones_status: auto            # 자동 구역. 확인해 고쳤으면 이 줄을 지운다 (그 뒤로 자동으로 안 고침)
zones:                        # [첫 쪽, 끝 쪽, 구역 이름, 포함]
  - [1, 6, 앞단, false]
  - [7, 110, 본문, true]
  - [111, 120, 부록, false]   # 자동 구역은 부록·중간 목차를 못 가른다 → 손으로 뺀다
eval:                         # 선택: 규칙 조정·검증용 쪽 (예시는 allinone_cancer_2_0.yaml)
```

- 구역 이름은 트리의 `zone` 노드 제목이 된다 (청킹 메타데이터로 쓸 수 있다). 같은 이름 구역은 한 노드로 합쳐진다.
- 구역을 처음부터 다시 자동으로 정하려면 `zones_status: provisional`로 바꾸고 다시 돌린다.
- 고친 뒤: `$PY parsing/run.py --doc <doc_id>` (덤프·쪽 그림은 다시 하지 않는다).

## 5. 임계값 조정

`config/params.yaml`의 주석이 각 값의 뜻과 맞춘 근거다. 한 문서만 다르면 문서 설정 `params`에 그 값만 적는다
(점으로 이은 이름 그대로 중첩: `tree.item_align_tol_pt` → `{tree: {item_align_tol_pt: 5}}`).
어느 단계부터 다시 돌릴지는 README "규칙을 고쳤을 때" 표.

## 6. 코드를 고쳐야 하는 경우

설정으로 안 되는 것:

| 상황 | 고칠 곳 |
|---|---|
| 번호 모양이 다름 (`Article 1`, `第1条`, `§ 1`, `1.1.`, `I.` 등) | `parsing/pdf_lines.py` `PATTERNS` (줄 맨 앞 번호 모양 → 패턴 이름), `parsing/tree.py` `ART_RE`·`ITEM_PATTERNS`·`item_number`, 참조는 `parsing/refs.py` `REF_RE` |
| 조문형이 아닌 문서 (보고서·매뉴얼·논문: "1. 개요" 같은 장 제목) | `parsing/tree.py` `build`: 지금은 조 (`article`)가 청킹 단위이고 "1."은 항목으로 본다. 제목 폰트 크기로 장·절 단계를 정하는 분기를 넣어야 한다. 덤프·표 추출·제외는 그대로 쓸 수 있다 |
| 스캔본 (글자 층 없음) | 지원하지 않음. OCR로 글자 층을 먼저 만든다 (`profile_source=no_text`로 나옴) |
| 2단 편집 (한 쪽에 두 열) | 같은 높이 글자를 한 줄로 묶고 (`parsing/pdf_lines.py` `build_lines`) 읽기 순서가 (쪽, 위, 왼쪽)이라 (`parsing/tree.py` `main`의 정렬 키) 두 열이 섞인다. 열을 먼저 나누는 처리가 필요하다 |
| 구역 자동 규칙을 문서 종류에 맞게 | `parsing/tools/zones.py` `candidate` (쪽 수치 → 구역 후보), `parsing/auto_zones.py` |

코드를 고칠 때 지킬 것 (`parsing/safeio.py`):
- 화면·로그 출력은 `out()`만 쓴다 (수치·라벨만 통과, 한글 원문은 막힌다). 원문이 든 파일은 `secure_path()`로 `secure/` 안에만 쓴다.
- 끝에 `leak` 단계가 `result=PASS`여야 한다.
- 이미 맞춰 둔 문서가 깨지지 않았는지 본다: 고치기 전에 그 문서의 `secure/<doc_id>/lines/regions.json`·`boxes.json`,
  `secure/<doc_id>/tables/*.jsonl`, `results/<doc_id>/parsing/excluded_regions.csv`를 `secure/<doc_id>/archive/verify_prev/`에
  복사해 두고, 고친 뒤 `PARSE_DOC=<doc_id> $PY parsing/tools/verify_same.py`로 비교한다 (해시·개수만 출력).
