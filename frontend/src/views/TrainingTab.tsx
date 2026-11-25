// 판단 훈련 탭 (FE-3): 검수 상태 + [시나리오 편집][다시 생성][검수 완료 표시], 시작 -> 단계 -> 결과.
import { useState } from "react";
import { api, BUSY_STATES, type ReportStatus, type Scenario } from "../api/client";
import { call, useLoad } from "../api/call";
import { Empty, ErrorBox, Loaded, LlmNotice, PageLink, Verified } from "../components/common";
import { figureNear, StepFigure, useFigures, type Fig } from "../components/Figures";
import { go, href } from "../route";

export default function TrainingTab({ id, reportState, hasRecord, onRegenerated }: {
  id: string;
  reportState: ReportStatus["state"];
  hasRecord: boolean;
  onRegenerated: () => void;
}) {
  const busy = BUSY_STATES.includes(reportState);
  const [figs] = useFigures(id);
  const [load, reload] = useLoad(
    () => call(api.GET("/api/reports/{rid}/scenario", { params: { path: { rid: id } } })),
    [id, busy],
  );
  const [msg, setMsg] = useState<string | null>(null);

  if (busy) {
    return <div className="card"><Empty><span className="spin" /> 시나리오를 만드는 중입니다. 끝나면 여기에 나타납니다.</Empty></div>;
  }

  async function regenerate() {
    if (!window.confirm("시나리오를 다시 생성할까요? 지금 시나리오(교관이 고친 내용 포함)는 새 초안으로 바뀝니다.")) return;
    // 서버리스에서는 이 요청이 생성이 끝날 때까지(수십 초) 열려 있다. 기다리지 않고 상태 폴링으로 진행을 본다.
    const pending = call(api.POST("/api/reports/{rid}/scenario/regenerate", { params: { path: { rid: id } } }));
    setMsg(null);
    window.setTimeout(onRegenerated, 800);
    const r = await pending;
    if (!r.ok) setMsg(r.message);
    onRegenerated();
  }

  async function markReviewed() {
    const r = await call(api.POST("/api/reports/{rid}/scenario/review", { params: { path: { rid: id } } }));
    setMsg(r.ok ? null : r.message);
    if (r.ok) void reload(true);
  }

  if (load.state === "error" && load.status === 404) {
    return (
      <div className="card">
        <Empty>
          {reportState === "done" ? "시나리오가 없습니다." : hasRecord ? "시나리오를 만들지 못했습니다." : "사고 정보 구조화가 끝나지 않아 시나리오가 없습니다."}
          {hasRecord && (
            <div className="mt"><button className="btn" onClick={() => void regenerate()}>시나리오 생성</button></div>
          )}
        </Empty>
      </div>
    );
  }

  return (
    <div className="card">
      <Loaded load={load} what="판단 훈련 시나리오" onRetry={() => void reload()}>
        {(sc) => (
          <>
            <div className="row">
              <span className={`tag ${sc.review_status === "검수 완료" ? "ok" : "warn"}`}>{sc.review_status}</span>
              {sc.role && <span className="tag">역할: {sc.role}</span>}
              <span className="grow" />
              <a className="btn sm" href={href.report(id, "edit")}>시나리오 편집</a>
              <button className="btn sm" onClick={() => void regenerate()}>다시 생성</button>
              <button className="btn sm" onClick={() => void markReviewed()} disabled={sc.review_status === "검수 완료"}>
                검수 완료 표시
              </button>
            </div>
            {msg && <ErrorBox message={msg} />}
            {sc.review_status === "검수 전" && (
              <div className="banner">교관 검수 전 초안입니다. 교육에 쓰기 전에 교관이 내용을 확인하세요.</div>
            )}
            <LlmNotice>시나리오는 보고서를 바탕으로 LLM이 작성했습니다. 원문과 대조하세요.</LlmNotice>
            <Player key={JSON.stringify(sc)} id={id} sc={sc} figs={figs.state === "ok" ? figs.data : []} />
          </>
        )}
      </Loaded>
    </div>
  );
}

function Player({ id, sc, figs }: { id: string; sc: Scenario; figs: Fig[] }) {
  const [step, setStep] = useState(-1); // -1 시작 화면, steps.length 결과
  const [picked, setPicked] = useState<(string | null)[]>(() => sc.steps.map(() => null));

  if (sc.steps.length === 0) return <Empty>판단 지점이 없는 시나리오입니다. 편집에서 단계를 추가하세요.</Empty>;

  if (step < 0) {
    return (
      <div className="player">
        <h2>{sc.title}</h2>
        <div className="situation">{sc.intro}</div>
        <p className="meta">판단 지점 {sc.steps.length}개</p>
        <button className="btn primary" onClick={() => setStep(0)}>훈련 시작</button>
      </div>
    );
  }

  if (step >= sc.steps.length) {
    const score = sc.steps.filter((s, i) => picked[i] === s.answer_id).length;
    return (
      <div className="player">
        <h2>결과: {score} / {sc.steps.length}</h2>
        <h3>마무리</h3>
        <div className="situation">{sc.debrief}</div>
        <div className="row mt">
          <button className="btn primary" onClick={() => { setPicked(sc.steps.map(() => null)); setStep(-1); }}>처음부터</button>
          <button className="btn" onClick={() => go(href.report(id))}>사고 정보 보기</button>
        </div>
      </div>
    );
  }

  const s = sc.steps[step];
  const mine = picked[step];
  const answered = mine !== null;
  const correct = mine === s.answer_id;

  return (
    <div className="player">
      <div className="progress">판단 지점 {step + 1} / {sc.steps.length}</div>
      <div className={`step-body ${figureNear(figs, s.evidence?.page) ? "with-fig" : ""}`}>
        <div className="situation">{s.situation}</div>
        <StepFigure rid={id} fig={figureNear(figs, s.evidence?.page)} />
      </div>
      <p className="question">{s.question}</p>
      {s.options.map((o) => {
        const cls = !answered ? "" : o.id === s.answer_id ? "correct" : o.id === mine ? "wrong" : "";
        return (
          <button key={o.id} className={`btn opt ${cls}`} disabled={answered}
            onClick={() => setPicked((p) => p.map((x, i) => (i === step ? o.id : x)))}>
            <b>{o.id}.</b> {o.text}
          </button>
        );
      })}
      {answered && (
        <div className={`feedback ${correct ? "ok" : "bad"}`}>
          <b>{correct ? "정답입니다" : `오답입니다 — 정답은 ${s.answer_id}`}</b>
          <div className="pre">{s.explanation}</div>
          {(s.rule_refs?.length ?? 0) > 0 && (
            <div className="mt">{s.rule_refs!.map((r) => <span key={r} className="tag">{r}</span>)}</div>
          )}
          <h4>실제 사고에서는</h4>
          <div className="pre">
            {s.what_happened}
            <PageLink rid={id} page={s.evidence?.page} />
            <Verified v={s.evidence?.verified} />
          </div>
          <div className="row mt">
            <button className="btn primary" onClick={() => setStep(step + 1)}>
              {step + 1 < sc.steps.length ? "다음" : "결과 보기"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
