// 사고 정보 탭 (FE-2): 비슷한 과거 사고 카드 + 공통점 요약 + 구조화 섹션 (모든 항목에 p.N 근거).
import { useState, type ReactNode } from "react";
import { api, type AccidentRecord, type Schemas } from "../api/client";
import { call, useLoad, type Result } from "../api/call";
import { clip, Empty, ErrorBox, EvidenceLine, Loaded, Loading, LlmNotice, Md, PageLink } from "../components/common";
import { href } from "../route";

export default function InfoTab({ id, record: r }: { id: string; record: AccidentRecord }) {
  // 목록 필드는 계약상 생략될 수 있다 (기본값 []).
  const record = {
    ...r,
    timeline: r.timeline ?? [], direct_causes: r.direct_causes ?? [], contributing_factors: r.contributing_factors ?? [],
    violated_rules: r.violated_rules ?? [], recommendations: r.recommendations ?? [], training_findings: r.training_findings ?? [],
  };
  return (
    <>
      <RelatedCard id={id} />
      <div className="card">
        <div className="banner">모든 항목은 LLM이 추출한 결과입니다. p.N을 눌러 원문과 대조하세요.</div>

        <Section title="개요" empty={!record.summary && !record.damage}>
          <p className="para">{record.summary}</p>
          {record.damage && <p className="para"><b>피해</b> {record.damage}</p>}
        </Section>

        <Section title="사고 경위" empty={record.timeline.length === 0}>
          <ul className="items">
            {record.timeline.map((t, i) => (
              <li key={i}>
                {t.time && <b className="time">{t.time}</b>} {t.event}
                <EvidenceLine rid={id} ev={t.evidence} />
              </li>
            ))}
          </ul>
        </Section>

        <ItemSection title="직접 원인" id={id} items={record.direct_causes} />
        <ItemSection title="기여요인" id={id} items={record.contributing_factors} />

        <Section title="지적된 규정·지침" empty={record.violated_rules.length === 0}>
          <ul className="items">
            {record.violated_rules.map((r, i) => (
              <li key={i}>
                <b>{r.rule_name}</b>{r.article && ` ${r.article}`} — {r.description}
                <EvidenceLine rid={id} ev={r.evidence} />
              </li>
            ))}
          </ul>
        </Section>

        <Section title="안전권고" empty={record.recommendations.length === 0}>
          <ul className="items">
            {record.recommendations.map((r, i) => (
              <li key={i}>
                {r.target && <span className="tag">{r.target}</span>}
                {r.text}
                <EvidenceLine rid={id} ev={r.evidence} />
              </li>
            ))}
          </ul>
        </Section>

        <ItemSection title="교육·훈련 관련 지적" id={id} items={record.training_findings} />
      </div>
    </>
  );
}

function Section({ title, empty, children }: { title: string; empty: boolean; children: ReactNode }) {
  return (
    <section>
      <h3>{title}</h3>
      {empty ? <div className="meta">보고서에서 찾지 못함</div> : children}
    </section>
  );
}

function ItemSection({ title, id, items }: { title: string; id: string; items: Schemas["Item"][] }) {
  return (
    <Section title={title} empty={items.length === 0}>
      <ul className="items">
        {items.map((it, i) => (
          <li key={i}>
            {it.text}
            <EvidenceLine rid={id} ev={it.evidence} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function RelatedCard({ id }: { id: string }) {
  const [load, reload] = useLoad(() => call(api.GET("/api/reports/{rid}/related", { params: { path: { rid: id } } })), [id]);
  const [summary, setSummary] = useState<Result<Schemas["AskResult"]> | "loading" | null>(null);

  async function compare() {
    setSummary("loading");
    setSummary(await call(api.POST("/api/reports/{rid}/compare", { params: { path: { rid: id } } })));
  }

  return (
    <div className="card">
      <h3 className="first">비슷한 과거 사고</h3>
      <Loaded load={load} what="비슷한 과거 사고" onRetry={() => void reload()}>
        {(groups) => groups.length === 0 ? (
          <Empty>비교할 과거 사고가 아직 없습니다. 보고서를 더 올리면 자동으로 연결됩니다.</Empty>
        ) : (
          <>
            <div className="related">
              {groups.map((g) => (
                <div key={g.report_id} className="rel">
                  <a className="t" href={href.report(g.report_id)}>{g.title}</a>
                  <div className="m">
                    {[g.accident_type, g.occurred_at].filter(Boolean).join(" · ")}
                    <span className="score"> 유사도 {g.score.toFixed(2)}</span>
                  </div>
                  {(g.shared_rules?.length ?? 0) > 0 && (
                    <div className="mt">
                      <span className="tag bad">이번에도 반복된 규정</span>
                      {g.shared_rules!.map((r) => <b key={r} className="rule">{r}</b>)}
                    </div>
                  )}
                  <ul className="hits">
                    {g.hits.slice(0, 3).map((h, i) => (
                      <li key={i}>
                        <span className="tag sm">{h.kind}</span>
                        {clip(h.text, 160)}
                        <PageLink rid={g.report_id} page={h.page} />
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <div className="row mt">
              <button className="btn" onClick={() => void compare()} disabled={summary === "loading"}>
                공통점 요약 (LLM)
              </button>
            </div>
            {summary === "loading" && <Loading text="LLM이 요약하는 중… (수십 초 걸릴 수 있음)" />}
            {summary && summary !== "loading" && (summary.ok ? (
              <div className="answer">
                <LlmNotice>검색된 과거 사고 조각만 근거로 LLM이 쓴 요약입니다. 원문과 대조하세요.</LlmNotice>
                <Md text={summary.data.answer} />
              </div>
            ) : <ErrorBox message={summary.message} onRetry={() => void compare()} />)}
          </>
        )}
      </Loaded>
    </div>
  );
}
