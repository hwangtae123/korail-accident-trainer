"""API 요청·응답 형식 (= 프론트와의 계약).

여기를 바꾸면 docs/openapi.json과 프론트 타입이 같이 바뀐다:
  python scripts/export_openapi.py        (backend/)
  npm run gen:api                         (frontend/)
계약 변경은 팀 리드와 합의한 뒤에만 한다. (CLAUDE.md 참고)
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .schema import AccidentRecord, Evidence

StatusState = Literal["queued", "parsing", "extracting", "indexing", "scenario", "done", "error", "ocr_needed"]


class ReportStatus(BaseModel):
    state: StatusState
    message: str = ""
    filename: str = ""
    ingested_at: str = Field("", description="접수 시각 ISO 8601 (마이크로초까지)")


class ReportSummary(BaseModel):
    id: str
    status: ReportStatus
    title: str
    report_no: str = ""
    accident_type: str = ""
    occurred_at: str = ""
    ingested_at: str = ""


class ReportDetail(BaseModel):
    status: ReportStatus
    record: Optional[AccidentRecord] = Field(None, description="구조화가 끝나기 전에는 null")


class UploadResult(BaseModel):
    id: str
    new: bool = Field(description="false면 같은 파일이 이미 있어서 다시 처리하지 않음")


class AppConfig(BaseModel):
    direct_upload: bool = Field(description="true면 PDF를 Supabase Storage에 직접 올린다 (upload-url -> PUT -> process). "
                                            "false면 POST /api/reports (multipart)")
    max_upload_mb: int = Field(description="올릴 수 있는 PDF 최대 크기 (MB)")


class UploadUrlRequest(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{10}$", description="PDF 내용 SHA-1 앞 10자리 (서버가 처리 전에 다시 계산해 확인)")
    filename: str = Field("", max_length=300)


class UploadUrlResult(BaseModel):
    id: str
    new: bool = Field(description="false면 같은 파일이 이미 있어서 올리지도 처리하지도 않는다")
    upload_url: Optional[str] = Field(None, description="new일 때만: 이 주소로 PDF를 PUT (Content-Type: application/pdf)")


class ProcessRequest(BaseModel):
    filename: str = Field("", max_length=300)


class Ok(BaseModel):
    ok: bool = True


class SearchHit(BaseModel):
    kind: str = Field(description="개요 | 경위 | 직접원인 | 기여요인 | 규정 | 안전권고 | 교육지적 | 본문")
    text: str
    score: float
    page: Optional[int] = None


class SearchGroup(BaseModel):
    report_id: str
    title: str
    score: float = Field(description="보고서 안에서 가장 가까운 조각의 코사인 유사도")
    hits: list[SearchHit]


class RelatedGroup(SearchGroup):
    shared_rules: list[str] = Field(default_factory=list, description="이번 사고에서도 지적된 같은 규정")
    accident_type: str = ""
    occurred_at: str = ""


class Query(BaseModel):
    q: str = Field(min_length=1)


class AskResult(BaseModel):
    answer: str
    groups: list[SearchGroup]


class NameCount(BaseModel):
    name: str
    count: int


class TrainingFinding(BaseModel):
    report_id: str
    report: str
    text: str


class Stats(BaseModel):
    reports: int
    accident_types: list[NameCount]
    violated_rules: list[NameCount]
    training_findings: list[TrainingFinding]


class ReindexResult(BaseModel):
    indexed: dict[str, int]


# ---------- 아직 구현 전 (docs/backlog.md) — 계약만 먼저 고정 ----------

class BriefingRequest(BaseModel):
    work: str = Field(min_length=1, description="오늘 할 작업 설명 (장소, 작업 종류, 장비)")


class ChecklistItem(BaseModel):
    text: str = Field(description="작업 전 확인할 항목 (과거 안전권고·기여요인에서 도출)")
    source_report_id: str
    source_title: str
    evidence: Evidence


class Briefing(BaseModel):
    work: str
    summary: str = Field(description="비슷한 과거 사고 요약 (근거 [제목 p.N] 포함)")
    checklist: list[ChecklistItem]
    similar: list[SearchGroup]
