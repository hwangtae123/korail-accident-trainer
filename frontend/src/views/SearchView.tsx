// 유사사고 검색 (FE-5): 상황 설명 -> 보고서별 카드, [검색 결과로 요약하기 (LLM)].
import { useState } from "react";
import { api, type Schemas } from "../api/client";
import { call, useLoad, type Result } from "../api/call";
import { clip, Empty, ErrorBox, Loaded, Loading, LlmNotice, Md, PageLink } from "../components/common";
import { go, href } from "../route";

export default function SearchView({ q }: { q: string }) {
  const [text, setText] = useState(q);
  return (
    <div>
      <div className="card">
        <h2>유사사고 검색</h2>
        <p className="meta">오늘 작업이나 상황을 적으면 비슷한 과거 사고를 찾습니다 (LLM 없이 검색만).</p>
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (text.trim()) go(href.search(text.trim())); }}>
          <input className="input grow" value={text} onChange={(e) => setText(e.target.value)}
            placeholder="예: 야간 선로 작업 중 인접선 열차 진입" />
          <button className="btn primary" disabled={!text.trim()}>검색</button>
        </form>
      </div>
      {q ? <Results key={q} q={q} /> : <div className="card"><Empty>검색어를 입력하세요.</Empty></div>}
    </div>
  );
}

function Results({ q }: { q: string }) {
  const [load, reload] = useLoad(() => call(api.POST("/api/search", { body: { q } })), [q]);
  const [ans, setAns] = useState<Result<Schemas["AskResult"]> | "loading" | null>(null);

  async function ask() {
    setAns("loading");
    setAns(await call(api.POST("/api/ask", { body: { q } })));
  }

  return (
    <Loaded load={load} what="유사사고 검색" onRetry={() => void reload()}>
      {(groups) => groups.length === 0 ? (
        <div className="card"><Empty>비슷한 사고를 찾지 못했습니다. 색인된 보고서가 없거나 검색어가 너무 짧을 수 있습니다.</Empty></div>
      ) : (
        <>
          <div className="card">
            <div className="row">
              <span className="grow meta">“{q}” — 보고서 {groups.length}건</span>
              <button className="btn" onClick={() => void ask()} disabled={ans === "loading"}>검색 결과로 요약하기 (LLM)</button>
            </div>
            {ans === "loading" && <Loading text="LLM이 요약하는 중…" />}
            {ans && ans !== "loading" && (ans.ok ? (
              <div className="answer">
                <LlmNotice>검색 결과만 근거로 LLM이 쓴 요약입니다. 원문과 대조하세요.</LlmNotice>
                <Md text={ans.data.answer} />
              </div>
            ) : <ErrorBox message={ans.message} onRetry={() => void ask()} />)}
          </div>
          {groups.map((g) => <GroupCard key={g.report_id} g={g} />)}
        </>
      )}
    </Loaded>
  );
}

export function GroupCard({ g }: { g: Schemas["SearchGroup"] }) {
  return (
    <div className="card">
      <div className="row">
        <a className="t grow" href={href.report(g.report_id)}><b>{g.title}</b></a>
        <span className="score">유사도 {g.score.toFixed(2)}</span>
      </div>
      <ul className="hits">
        {g.hits.map((h, i) => (
          <li key={i}>
            <span className="tag sm">{h.kind}</span>
            {clip(h.text, 220)}
            <PageLink rid={g.report_id} page={h.page} />
          </li>
        ))}
      </ul>
    </div>
  );
}
