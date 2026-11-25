"""파싱한 보고서 -> AccidentRecord (구조화) -> Scenario (판단 훈련)."""
from .llm import complete_json
from .parse import ParsedReport
from .schema import AccidentRecord, Scenario

# 섹션별 최대 글자 수. 보고서 전체(50~60쪽)를 다 넣지 않고 필요한 부분만 넣는다.
LIMITS = {"timeline": 15000, "causes": 6000, "findings": 12000, "recommendations": 8000}

EXTRACT_SYSTEM = """당신은 철도 사고조사보고서를 구조화하는 분석가입니다.
규칙:
- 보고서에 적힌 내용만 쓰세요. 추측하거나 보고서에 없는 사실을 만들지 마세요. 없으면 빈 값으로 두세요.
- 모든 항목의 evidence.page에는 근거가 있는 쪽 번호([p.N] 표시)를, evidence.quote에는 원문 구절을 40자 이내로 넣으세요.
- direct_causes는 보고서 '사고원인'의 직접 원인, contributing_factors는 기여요인(➊➋… 번호)을 하나씩 나누세요.
- violated_rules는 보고서가 지키지 않았다고 지적한 규정·지침·내규만 넣으세요.
- training_findings에는 교육·훈련과 관련된 조사결과만 넣으세요.
- accident_type은 충돌/탈선/열차화재/사상/건널목/철도안전사고/기타 중 하나."""

SCENARIO_SYSTEM = """당신은 철도 안전교육 교관을 돕는 교육 설계자입니다.
실제 사고조사보고서의 경위를 바탕으로, 교육생이 사고 직전 각 판단 지점에서 무엇을 해야 하는지 연습하는 단계별 시나리오를 만듭니다.
규칙:
- 상황(situation)은 보고서 경위에 있는 사실로만 구성하세요. 장소·시각·속도 등 수치를 지어내지 마세요.
- 판단 지점은 3~5개. 사고로 이어진 실제 판단 실수나 누락이 있었던 지점을 고르세요.
- 선택지는 3~4개, 정답은 하나. 오답은 현장에서 실제로 할 법한 그럴듯한 행동으로 만드세요.
- 정답과 explanation은 보고서의 분석·사고원인·안전권고·규정에서 근거를 찾으세요. rule_refs에 규정 이름을 넣으세요.
- what_happened에는 실제 사고에서 어떻게 했고 무엇으로 이어졌는지 쓰세요.
- 교육생이 맡을 역할(role)은 판단 실수가 있었던 관계자 중 한 명으로 정하세요.
- 시나리오는 교관이 검수한 뒤 사용합니다. review_status는 "검수 전"."""


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n…(이하 생략)"


def _sections_for_extract(report: ParsedReport) -> str:
    s = report.sections
    head = "\n".join(report.pages[:3])  # 표지·개요
    parts = [f"## 앞부분(표지·개요)\n{_clip(head, 5000)}"]
    for key, label in [("timeline", "사고 경위"), ("findings", "조사결과"),
                       ("causes", "사고원인"), ("recommendations", "안전권고")]:
        if key in s:
            parts.append(f"## {label}\n{_clip(s[key], LIMITS[key])}")
    if len(parts) == 1:  # 목차를 못 찾았으면 앞에서부터 넣는다
        parts.append(f"## 본문\n{_clip(report.full_text, 40000)}")
    return "\n\n".join(parts)


def extract_record(report: ParsedReport) -> AccidentRecord:
    return complete_json(EXTRACT_SYSTEM, _sections_for_extract(report), AccidentRecord)


def build_scenario(report: ParsedReport, record: AccidentRecord) -> Scenario:
    s = report.sections
    user = (
        f"## 구조화된 사고 정보\n{record.model_dump_json(indent=1)}\n\n"
        f"## 사고 경위 원문\n{_clip(s.get('timeline') or s.get('facts', ''), LIMITS['timeline'])}\n\n"
        f"## 분석 원문(앞부분)\n{_clip(s.get('analysis', ''), 10000)}"
    )
    return complete_json(SCENARIO_SYSTEM, user, Scenario)
