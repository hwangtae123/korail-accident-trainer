// 작업 전 브리핑 TBM (FE-6): 오늘 작업 -> 과거 사고 요약 + 확인 항목 체크리스트 + 비슷한 사고. [인쇄] A4 한 장.
import { useState } from "react";
import { api, type Briefing } from "../api/client";
import { call, type Result } from "../api/call";
import { Empty, ErrorBox, Loading, LlmNotice, Md, NotReady, PageLink, Verified } from "../components/common";
import { href } from "../route";

export default function BriefingView() {
  const [place, setPlace] = useState("");
  const [kind, setKind] = useState("");
  const [equip, setEquip] = useState("");
  const [res, setRes] = useState<Result<Briefing> | "loading" | null>(null);

  const work = [place && `장소: ${place}`, kind && `작업: ${kind}`, equip && `장비: ${equip}`].filter(Boolean).join(" / ");

  async function run() {
    setRes("loading");
    setRes(await call(api.POST("/api/briefing", { body: { work } })));
  }

  return (
    <div className="briefing">
      <div className="card no-print">
        <h2>작업 전 브리핑 (TBM)</h2>
        <p className="meta">오늘 작업을 적으면 비슷한 과거 사고의 안전권고·기여요인에서 확인 항목을 뽑습니다.</p>
        <form onSubmit={(e) => { e.preventDefault(); if (work) void run(); }}>
          <div className="grid3">
            <label className="field">장소<input className="input" value={place} onChange={(e) => setPlace(e.target.value)} placeholder="예: ○○역 구내 2번선" /></label>
            <label className="field">작업 종류<input className="input" value={kind} onChange={(e) => setKind(e.target.value)} placeholder="예: 야간 선로 보수" /></label>
            <label className="field">장비<input className="input" value={equip} onChange={(e) => setEquip(e.target.value)} placeholder="예: 모터카, 궤도검측차" /></label>
          </div>
          <div className="row mt">
            <button className="btn primary" disabled={!work || res === "loading"}>브리핑 만들기</button>
            {res && res !== "loading" && res.ok && <button type="button" className="btn" onClick={() => window.print()}>인쇄</button>}
          </div>
        </form>
      </div>

      {res === "loading" && <div className="card"><Loading text="비슷한 사고를 찾고 확인 항목을 만드는 중… (LLM, 수십 초)" /></div>}
      {res && res !== "loading" && !res.ok && (
        <div className="card">{res.status === 501 ? <NotReady what="작업 전 브리핑" /> : <ErrorBox message={res.message} onRetry={() => void run()} />}</div>
      )}
      {res && res !== "loading" && res.ok && <Sheet b={res.data} />}
    </div>
  );
}

function Sheet({ b }: { b: Briefing }) {
  const today = new Date().toLocaleDateString("ko-KR");
  return (
    <div className="card sheet">
      <div className="sheet-head">
        <h2>작업 전 안전 브리핑</h2>
        <div className="meta">{today}</div>
      </div>
      <h3>오늘 작업</h3>
      <p className="para">{b.work}</p>

      {b.similar.length === 0 ? (
        <Empty>비슷한 과거 사고를 찾지 못했습니다 (색인된 보고서가 없을 수 있습니다).</Empty>
      ) : (
        <>
          <h3>비슷한 과거 사고 요약</h3>
          <LlmNotice />
          <Md text={b.summary || "요약 없음"} />

          <h3>작업 전 확인 항목</h3>
          {b.checklist.length === 0 ? (
            <div className="meta">과거 사고 권고에서 오늘 작업과 관련된 확인 항목을 찾지 못했습니다.</div>
          ) : (
            <ul className="checklist">
              {b.checklist.map((c, i) => (
                <li key={i}>
                  <label>
                    <input type="checkbox" /> <span className="box" aria-hidden />
                    <span>{c.text}</span>
                  </label>
                  <div className="src">
                    출처: <a href={href.report(c.source_report_id)}>{c.source_title}</a>
                    <PageLink rid={c.source_report_id} page={c.evidence.page} />
                    <Verified v={c.evidence.verified} />
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h3>비슷한 사고</h3>
          <ul className="items">
            {b.similar.map((g) => (
              <li key={g.report_id}>
                <a href={href.report(g.report_id)}>{g.title}</a> <span className="score">유사도 {g.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="print-foot">출처: 사조위 사고조사보고서, LLM 요약 — 원문 대조 필요</div>
    </div>
  );
}
