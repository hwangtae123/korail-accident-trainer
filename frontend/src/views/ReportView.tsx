// 보고서 상세: 머리(제목·메타·태그·원문 PDF) + 처리 상태 + 탭 [사고 정보 | 판단 훈련].
import { useEffect } from "react";
import { api, BUSY_STATES, pdfUrl } from "../api/client";
import { call, useLoad } from "../api/call";
import { ErrorBox, Loading, STATE_LABEL } from "../components/common";
import { href } from "../route";
import InfoTab from "./InfoTab";
import ScenarioEditor from "./ScenarioEditor";
import TrainingTab from "./TrainingTab";

const POLL_MS = 3000;

export default function ReportView({ id, tab, onChanged }: {
  id: string;
  tab: "info" | "train" | "edit";
  onChanged: () => void;
}) {
  const [load, reload] = useLoad(() => call(api.GET("/api/reports/{rid}", { params: { path: { rid: id } } })), [id]);
  const state = load.state === "ok" ? load.data.status.state : null;
  const busy = state !== null && BUSY_STATES.includes(state);

  // 처리 중이면 3초마다 다시 불러온다.
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => void reload(true), POLL_MS);
    return () => window.clearInterval(t);
  }, [busy, reload]);

  // 상태가 바뀌면 왼쪽 목록의 상태 태그도 갱신한다.
  useEffect(() => {
    if (state) onChanged();
  }, [state, onChanged]);

  if (load.state === "loading") return <Loading />;
  if (load.state === "error") {
    return <ErrorBox message={load.status === 404 ? "없는 보고서입니다." : load.message} onRetry={() => void reload()} />;
  }

  const { status, record } = load.data;
  const meta = record ? [record.report_no, record.occurred_at, record.location].filter(Boolean).join(" · ") : "";

  return (
    <div>
      <div className="card">
        <h2>{record?.title || status.filename || id}</h2>
        {meta && <div className="meta">{meta}</div>}
        <div className="row mt">
          {record?.accident_type && <span className="tag">{record.accident_type}</span>}
          {record?.vehicles?.map((v) => <span key={v} className="tag">{v}</span>)}
          <a className="btn sm" href={pdfUrl(id)} target="_blank" rel="noreferrer">원문 PDF</a>
        </div>

        <ProcessingStatus state={status.state} message={status.message} />

        <div className="tabs">
          <a className={`btn ${tab === "info" ? "on" : ""}`} href={href.report(id)}>사고 정보</a>
          <a className={`btn ${tab !== "info" ? "on" : ""}`} href={href.report(id, "train")}>판단 훈련</a>
        </div>
      </div>

      {tab === "info" && (record
        ? <InfoTab id={id} record={record} />
        : <div className="card"><div className="empty">{busy ? "구조화가 끝나면 사고 정보가 나타납니다." : "사고 정보가 없습니다."}</div></div>)}
      {tab === "train" && (
        <TrainingTab id={id} reportState={status.state} hasRecord={!!record}
          onRegenerated={() => { void reload(true); onChanged(); }} />
      )}
      {tab === "edit" && <ScenarioEditor id={id} />}
    </div>
  );
}

function ProcessingStatus({ state, message }: { state: string; message: string }) {
  if (state === "done") return null;
  if (state === "ocr_needed") {
    return (
      <div className="banner warn">
        텍스트를 읽을 수 없는 PDF(OCR 필요), LLM 호출 없이 건너뜀. <span className="meta">{message}</span>
      </div>
    );
  }
  if (state === "error") return <div className="banner bad">처리 오류: {message}</div>;
  const steps = ["queued", "parsing", "extracting", "indexing", "scenario"] as const;
  const cur = steps.indexOf(state as (typeof steps)[number]);
  return (
    <div className="banner info">
      <div className="steps">
        {steps.map((s, i) => (
          <span key={s} className={i < cur ? "done" : i === cur ? "cur" : ""}>
            {STATE_LABEL[s]}
          </span>
        ))}
      </div>
      <span className="spin" /> {message || "처리 중"} <span className="meta">(3초마다 갱신)</span>
    </div>
  );
}
