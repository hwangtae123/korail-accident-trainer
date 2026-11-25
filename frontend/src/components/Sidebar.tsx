// 왼쪽 영역 (FE-1): PDF 올리기, 유사사고 검색 입력, 보고서 목록, 메뉴.
import { useState } from "react";
import type { ReportSummary } from "../api/client";
import type { Load } from "../api/call";
import { go, href, type Route } from "../route";
import { useUpload } from "../useUpload";
import { Empty, ErrorBox, fmtTime, Loading, StatusTag } from "./common";

export default function Sidebar({ route, reports, onUploaded, onRetry }: {
  route: Route;
  reports: Load<ReportSummary[]>;
  onUploaded: () => void;
  onRetry: () => void;
}) {
  const { busy, notes, upload } = useUpload(onUploaded);
  const [q, setQ] = useState(route.name === "search" ? route.q : "");

  const activeId = route.name === "report" ? route.id : null;

  return (
    <aside className="side no-print">
      <div className="card">
        <h3>PDF 올리기</h3>
        <label className={`drop ${busy ? "disabled" : ""}`}>
          <input type="file" accept="application/pdf,.pdf" multiple disabled={busy}
            onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
          {busy ? "올리는 중…" : "사고조사보고서 PDF 선택 (여러 개 가능)"}
        </label>
        {notes.length > 0 && (
          <ul className="notes">
            {notes.map((n, i) => (
              <li key={i} className={n.kind}>
                <b>{n.name}</b> {n.text}
                {n.id && <a href={href.report(n.id)}> 열기</a>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h3>유사사고 검색</h3>
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (q.trim()) go(href.search(q.trim())); }}>
          <input className="input grow" value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="예: 야간 선로 작업 중 인접선 열차 진입" />
          <button className="btn primary" disabled={!q.trim()}>검색</button>
        </form>
      </div>

      <div className="card">
        <h3>보고서 목록 {reports.state === "ok" && <span className="meta">{reports.data.length}건</span>}</h3>
        {reports.state === "loading" && <Loading />}
        {reports.state === "error" && <ErrorBox message={reports.message} onRetry={onRetry} />}
        {reports.state === "ok" && reports.data.length === 0 && <Empty>아직 올린 보고서가 없습니다.</Empty>}
        {reports.state === "ok" && reports.data.map((r) => (
          <a key={r.id} href={href.report(r.id)} className={`list-item ${activeId === r.id ? "active" : ""}`}>
            <div className="t">{r.title}</div>
            <div className="m">
              {[r.report_no, r.occurred_at].filter(Boolean).join(" · ")}
            </div>
            <div className="m">접수 {fmtTime(r.ingested_at)}</div>
            <div className="tags">
              {r.accident_type && <span className="tag">{r.accident_type}</span>}
              <StatusTag state={r.status.state} />
            </div>
          </a>
        ))}
      </div>
    </aside>
  );
}
