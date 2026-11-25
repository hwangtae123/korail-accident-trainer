// 타입이 붙은 API 클라이언트. 타입은 docs/openapi.json에서 생성된다 (npm run gen:api).
// schema.d.ts는 손으로 고치지 않는다. 계약이 바뀌면 백엔드가 export -> 여기서 gen:api.
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** 백엔드 주소. 비우면 같은 주소의 /api (개발: Vite 프록시, Docker: FastAPI가 화면도 내보냄).
 *  Vercel처럼 화면을 따로 배포하면 VITE_API_BASE=https://백엔드주소 (끝 / 없이). 빌드할 때 들어간다. */
export const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

export const api = createClient<paths>({ baseUrl: API_BASE });

export type Schemas = components["schemas"];
export type ReportSummary = Schemas["ReportSummary"];
export type ReportDetail = Schemas["ReportDetail"];
export type ReportStatus = Schemas["ReportStatus"];
export type AccidentRecord = Schemas["AccidentRecord"];
export type Scenario = Schemas["Scenario"];
export type RelatedGroup = Schemas["RelatedGroup"];
export type SearchGroup = Schemas["SearchGroup"];
export type Stats = Schemas["Stats"];
export type Briefing = Schemas["Briefing"];

/** 원문 PDF의 특정 쪽 링크 (근거 확인용) */
export const pdfUrl = (rid: string, page?: number | null) =>
  `${API_BASE}/api/reports/${rid}/pdf${page ? `#page=${page}` : ""}`;

/** 처리 중 상태 (이 상태면 폴링을 계속한다) */
export const BUSY_STATES: ReportStatus["state"][] = ["queued", "parsing", "extracting", "indexing", "scenario"];
