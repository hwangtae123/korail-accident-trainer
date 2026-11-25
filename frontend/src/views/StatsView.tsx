// 반복 패턴 (FE-7): 보고서 수, 사고 유형별 건수, 지적된 규정 상위 20개(막대), 교육·훈련 관련 지적.
import { api } from "../api/client";
import { call, useLoad } from "../api/call";
import { Empty, Loaded } from "../components/common";
import { href } from "../route";

export default function StatsView() {
  const [load, reload] = useLoad(() => call(api.GET("/api/stats")), []);
  return (
    <Loaded load={load} what="반복 패턴" onRetry={() => void reload()}>
      {(s) => s.reports === 0 ? (
        <div className="card"><h2>반복 패턴</h2><Empty>구조화가 끝난 보고서가 없습니다.</Empty></div>
      ) : (
        <>
          <div className="card">
            <div className="row">
              <h2 className="grow">반복 패턴</h2>
              <button className="btn sm" onClick={() => void reload()}>새로 고침</button>
            </div>
            <div className="kpis">
              <div className="kpi"><div className="n">{s.reports}</div><div className="l">보고서</div></div>
              {s.accident_types.map((t) => (
                <div key={t.name} className="kpi"><div className="n">{t.count}</div><div className="l">{t.name}</div></div>
              ))}
            </div>
          </div>
          <div className="card">
            <h3 className="first">지적된 규정·지침 (상위 20개, 보고서 수)</h3>
            {s.violated_rules.length === 0 ? <Empty>지적된 규정이 없습니다.</Empty> : (
              <Bars rows={s.violated_rules} />
            )}
          </div>
          <div className="card">
            <h3 className="first">교육·훈련 관련 지적 ({s.training_findings.length}건)</h3>
            {s.training_findings.length === 0 ? <Empty>교육·훈련 관련 지적이 없습니다.</Empty> : (
              <ul className="items">
                {s.training_findings.map((t, i) => (
                  <li key={i}>{t.text} <a className="src" href={href.report(t.report_id)}>— {t.report}</a></li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Loaded>
  );
}

function Bars({ rows }: { rows: { name: string; count: number }[] }) {
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.name} className="bar-row">
          <div className="bar-label" title={r.name}>{r.name}</div>
          <div className="bar-track"><div className="bar" style={{ width: `${(r.count / max) * 100}%` }} /></div>
          <div className="bar-n">{r.count}</div>
        </div>
      ))}
    </div>
  );
}
