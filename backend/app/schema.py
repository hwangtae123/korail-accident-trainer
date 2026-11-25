"""사고조사보고서 구조화 결과와 판단 훈련 시나리오의 데이터 형식."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

AccidentType = Literal["충돌", "탈선", "열차화재", "사상", "건널목", "철도안전사고", "기타"]


class Evidence(BaseModel):
    """모든 추출 항목에 붙는 근거. 사람이 원문과 대조할 수 있게 쪽 번호를 남긴다."""
    page: Optional[int] = Field(None, description="근거가 있는 보고서 쪽 번호")
    quote: str = Field("", description="원문에서 근거가 되는 짧은 구절 (40자 이내)")
    verified: Optional[bool] = Field(
        None, description="quote가 해당 쪽 원문에 실제로 있는지 코드로 대조한 결과. null = 아직 확인 안 함")


class Item(BaseModel):
    text: str
    evidence: Evidence = Evidence()


class ViolatedRule(BaseModel):
    rule_name: str = Field(description="규정·지침 이름 (예: 선로유지관리지침)")
    article: str = Field("", description="조·항 (보고서에 있을 때만)")
    description: str = Field(description="무엇을 지키지 않았는지")
    evidence: Evidence = Evidence()


class Recommendation(BaseModel):
    target: str = Field(description="권고 대상 기관")
    text: str
    evidence: Evidence = Evidence()


class TimelineEvent(BaseModel):
    time: str = Field("", description="시각 (보고서에 있을 때만, 예: 02:16)")
    event: str
    evidence: Evidence = Evidence()


class AccidentRecord(BaseModel):
    report_no: str = Field("", description="보고서 번호 (예: ARAIB/R 2026-8)")
    title: str
    occurred_at: str = Field("", description="발생 일시")
    location: str = ""
    accident_type: AccidentType = "기타"
    vehicles: list[str] = Field(default_factory=list, description="관련 열차·차량·장비")
    summary: str = Field(description="사고 개요 2~3문장")
    damage: str = ""
    timeline: list[TimelineEvent] = Field(default_factory=list)
    direct_causes: list[Item] = Field(default_factory=list)
    contributing_factors: list[Item] = Field(default_factory=list)
    violated_rules: list[ViolatedRule] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    training_findings: list[Item] = Field(default_factory=list, description="교육·훈련 관련 조사결과")


class Option(BaseModel):
    id: str
    text: str


class ScenarioStep(BaseModel):
    situation: str = Field(description="이 단계에서 교육생이 마주한 상황")
    question: str
    options: list[Option]
    answer_id: str
    explanation: str = Field(description="올바른 판단과 그 이유")
    rule_refs: list[str] = Field(default_factory=list, description="근거 규정")
    what_happened: str = Field(description="실제 사고에서는 어떻게 했고 어떤 결과로 이어졌는지")
    evidence: Evidence = Evidence()


class Scenario(BaseModel):
    title: str
    role: str = Field(description="교육생이 맡는 역할 (예: 장비 운전원)")
    intro: str
    steps: list[ScenarioStep]
    debrief: str = Field(description="마무리: 사고원인과 교훈 요약")
    review_status: Literal["검수 전", "검수 완료"] = "검수 전"
