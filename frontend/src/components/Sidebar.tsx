// 왼쪽 영역 (FE-1): PDF 올리기, 유사사고 검색 입력, 보고서 목록, 메뉴.
import { useState } from "react";
import { api, type ReportSummary } from "../api/client";
import { call, type Load } from "../api/call";
import { go, href, type Route } from "../route";
import { Empty, ErrorBox, fmtTime, Loading, StatusTag } from "./common";

type UploadNote = { name: string; text: string; kind: "ok" | "warn" | "bad"; id?: string };

export default function Sidebar({ route, reports, onUploaded, onRetry }: {
  route: Route;
  reports: Load<ReportSummary[]>;
  onUploaded: () => void;
  onRetry: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<UploadNote[]>([]);
  const [q, setQ] = useState(route.name === "search" ? route.q : "");

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    const out: UploadNote[] = [];
    for (const f of Array.from(files)) {
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        out.push({ name: f.name, text: "PDF 파일이 아님 — 건너뜀", kind: "bad" });
        continue;
      }
      const r = await call(api.POST("/api/reports", {
        body: { file: f as unknown as string },
        bodySerializer: () => {
          const fd = new FormData();
          fd.append("file", f);
          return fd;
        },
      }));
      if (!r.ok) out.push({ name: f.name, text: r.message, kind: "bad" });
      else if (r.data.new) out.push({ name: f.name, text: "접수됨 — 처리 시작", kind: "ok", id: r.data.id });
      else out.push({ name: f.name, text: "이미 있는 보고서입니다 — 기존 결과를 엽니다", kind: "warn", id: r.data.id });
    }
    setNotes(out);
    setBusy(false);
    onUploaded();
    const first = out.find((n) => n.id);
    if (first?.id) go(href.report(first.id));
  }

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
        <nav className="menu">
          <a className={route.name === "stats" ? "on" : ""} href={href.stats()}>반복 패턴</a>
          <a className={route.name === "briefing" ? "on" : ""} href={href.briefing()}>작업 전 브리핑</a>
        </nav>
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
