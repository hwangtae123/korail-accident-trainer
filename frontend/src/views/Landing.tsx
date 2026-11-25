// 첫 화면: 히어로(파란 그라디언트 + 아이소메트릭 열차) · 네 가지 도구 · 최근 분석한 사고 · 근거 원칙.
import type { ReactNode } from "react";
import { api, type ReportSummary } from "../api/client";
import { call, useLoad, type Load } from "../api/call";
import { ErrorBox, fmtTime, Loading, StatusTag } from "../components/common";
import IsoTrain from "../components/IsoTrain";
import { RailMark } from "../components/TopNav";
import { href } from "../route";
import type { UploadNote } from "../useUpload";

export default function Landing({ reports, trainHref, uploading, notes, onUpload, onRetry }: {
  reports: Load<ReportSummary[]>;
  trainHref: string | null;
  uploading: boolean;
  notes: UploadNote[];
  onUpload: (files: FileList | null) => void;
  onRetry: () => void;
}) {
  const [stats] = useLoad(() => call(api.GET("/api/stats")), []);
  const n = reports.state === "ok" ? reports.data.filter((r) => r.status.state === "done").length : null;
  const topRule = stats.state === "ok" ? stats.data.violated_rules[0] : undefined;

  return (
    <div className="landing">
      <section className="hero">
        <div className="hero-grid" aria-hidden="true" />
        <div className="hero-in">
          <a className="hero-badge" href={href.stats()}>
            <span className="new">NEW</span>
            {n ? `실제 사고조사보고서 ${n}건 분석 완료` : "사고조사보고서를 올리면 바로 분석합니다"}
            <span className="more">반복 패턴 보기 →</span>
          </a>
          <h1>사고는 반복됩니다.<br />판단은 훈련할 수 있습니다.</h1>
          <p className="hero-sub">
            항공·철도사고조사위원회 보고서를 원문 쪽 번호 근거와 함께 정리하고,<br className="br-wide" />
            사고 직전의 판단 지점을 교육생이 직접 연습합니다.
          </p>
          <div className="hero-cta">
            <a className="cta white" href={trainHref ?? href.briefing()}>
              {trainHref ? "판단 훈련 시작" : "작업 전 브리핑"}
              <span className="arrow" aria-hidden="true">→</span>
            </a>
            <a className="cta blue" href={trainHref ? href.briefing() : href.search("")}>
              {trainHref ? "작업 전 브리핑" : "유사사고 검색"}
            </a>
          </div>
        </div>
        <div className="hero-art"><IsoTrain /></div>
      </section>

      <section className="band">
        <div className="band-in">
          <Stat n={n ?? "–"} label="분석한 사고조사보고서" />
          <Stat n={stats.state === "ok" ? stats.data.accident_types.map((t) => t.name).join(" · ") || "–" : "–"} label="사고 유형" small />
          <Stat n={topRule ? `${topRule.count}건` : "–"} label={topRule ? `가장 많이 지적된 규정 · ${topRule.name}` : "가장 많이 지적된 규정"} />
          <Stat n={stats.state === "ok" ? `${stats.data.training_findings.length}건` : "–"} label="교육·훈련 관련 지적" />
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <span className="eyebrow">교관 · 교육생 · 현장 작업책임자</span>
          <h2>보고서 한 권이 교육 네 가지가 됩니다</h2>
        </div>
        <div className="features">
          <Feature icon="doc" title="근거 있는 사고 정보 카드"
            text="경위·원인·기여요인·지적 규정·안전권고를 뽑고, 항목마다 원문 쪽(p.N)과 원문 대조 결과(✓)를 붙입니다." />
          <Feature icon="steps" title="단계별 판단 훈련" to={trainHref ?? undefined}
            text="사고 직전 판단 지점 3~5개를 시나리오로. 교관이 검수·편집한 뒤 교육에 씁니다." />
          <Feature icon="link" title="비슷한 과거 사고 · 반복 규정" to={href.stats()}
            text="새 보고서가 들어오면 비슷한 과거 사고와 '이번에도 반복된 규정'을 바로 연결합니다." />
          <Feature icon="check" title="작업 전 브리핑(TBM)" to={href.briefing()}
            text="오늘 작업을 적으면 과거 사고 권고에서 확인 항목을 뽑아 A4 한 장으로 인쇄합니다." />
        </div>
      </section>

      <section className="section alt">
        <div className="section-head row-head">
          <div>
            <span className="eyebrow">최근 분석</span>
            <h2>최근 분석한 사고</h2>
          </div>
          <a className="link-more" href={href.search("")}>유사사고 검색 →</a>
        </div>
        {reports.state === "loading" && <Loading />}
        {reports.state === "error" && <ErrorBox message={reports.message} onRetry={onRetry} />}
        {reports.state === "ok" && (
          <div className="report-grid">
            {reports.data.slice(0, 5).map((r) => <ReportCard key={r.id} r={r} />)}
            <label className={`report-card upload ${uploading ? "disabled" : ""}`}>
              <input type="file" accept="application/pdf,.pdf" multiple disabled={uploading}
                onChange={(e) => { onUpload(e.target.files); e.target.value = ""; }} />
              <span className="plus" aria-hidden="true">+</span>
              <b>{uploading ? "올리는 중…" : "새 보고서 올리기"}</b>
              <span className="meta">사고조사보고서 PDF (여러 개 가능). 분석에 1~2분</span>
              {notes.length > 0 && (
                <ul className="notes">{notes.map((x, i) => <li key={i} className={x.kind}><b>{x.name}</b> {x.text}</li>)}</ul>
              )}
            </label>
          </div>
        )}
      </section>

      <section className="section trust">
        <div className="trust-card">
          <RailMark size={40} />
          <div>
            <h3>근거 없는 내용은 만들지 않습니다</h3>
            <p>
              모든 사고 정보에는 원문 쪽 번호가 붙고, 그 구절이 실제로 원문에 있는지 코드가 대조합니다.
              LLM이 쓴 요약·시나리오에는 "원문과 대조하세요" 안내가 붙고, 시나리오는 교관 검수 전까지 초안으로 표시됩니다.
            </p>
          </div>
        </div>
      </section>

      <footer className="foot">
        <span>출처: 항공·철도사고조사위원회 철도 사고조사보고서 · LLM 결과는 원문 대조 필요</span>
        <span>철도 안전교육용 해커톤 프로토타입</span>
      </footer>
    </div>
  );
}

function Stat({ n, label, small }: { n: ReactNode; label: string; small?: boolean }) {
  return (
    <div className="stat">
      <div className={`n ${small ? "small" : ""}`}>{n}</div>
      <div className="l" title={label}>{label}</div>
    </div>
  );
}

const ICONS: Record<string, ReactNode> = {
  doc: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />,
  steps: <path d="M4 18h5v-5h5V8h5V4M4 18v2M19 4h1" />,
  link: <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />,
  check: <path d="M5 4h14v16H5zM8.5 10l2 2 4-4M8.5 16h7" />,
};

function Feature({ icon, title, text, to }: { icon: string; title: string; text: string; to?: string }) {
  const body = (
    <>
      <span className="ficon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8"
          strokeLinecap="round" strokeLinejoin="round">{ICONS[icon]}</svg>
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {to && <span className="fmore">열기 →</span>}
    </>
  );
  return to ? <a className="feature" href={to}>{body}</a> : <div className="feature">{body}</div>;
}

function ReportCard({ r }: { r: ReportSummary }) {
  return (
    <a className="report-card" href={href.report(r.id)}>
      <div className="rc-top">
        {r.accident_type && <span className="tag">{r.accident_type}</span>}
        <StatusTag state={r.status.state} />
      </div>
      <b className="rc-title">{r.title}</b>
      <span className="meta">{[r.report_no, r.occurred_at].filter(Boolean).join(" · ") || `접수 ${fmtTime(r.ingested_at)}`}</span>
    </a>
  );
}
