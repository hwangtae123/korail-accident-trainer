// 레이아웃: 상단 바 + 왼쪽(올리기·검색·목록·메뉴) + 오른쪽(선택한 화면). 화면은 주소 해시로 고른다 (route.ts).
import { useCallback, useEffect } from "react";
import { api, BUSY_STATES } from "./api/client";
import { call, useLoad } from "./api/call";
import { Empty } from "./components/common";
import Sidebar from "./components/Sidebar";
import { useRoute } from "./route";
import BriefingView from "./views/BriefingView";
import ReportView from "./views/ReportView";
import SearchView from "./views/SearchView";
import StatsView from "./views/StatsView";

const POLL_MS = 3000;

export default function App() {
  const route = useRoute();
  const [reports, reloadReports] = useLoad(() => call(api.GET("/api/reports")), []);
  const refresh = useCallback(() => void reloadReports(true), [reloadReports]);

  // 목록에 처리 중인 보고서가 있으면 3초마다 목록을 다시 불러온다 (상태 태그 갱신).
  const anyBusy = reports.state === "ok" && reports.data.some((r) => BUSY_STATES.includes(r.status.state));
  useEffect(() => {
    if (!anyBusy) return;
    const t = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(t);
  }, [anyBusy, refresh]);

  return (
    <>
      <header className="top no-print">
        <a href="#/"><h1>사고사례 판단 훈련</h1></a>
        <span>철도 사고조사보고서 기반 교육 · 해커톤 프로토타입</span>
      </header>
      <div className={`wrap ${route.name === "home" ? "" : "has-view"}`}>
        <Sidebar route={route} reports={reports} onUploaded={refresh} onRetry={() => void reloadReports()} />
        <main>
          {route.name === "home" && (
            <div className="card">
              <h2>사고사례 판단 훈련</h2>
              <Empty>
                왼쪽에서 보고서를 고르거나 PDF를 올리세요.<br />
                올린 보고서는 파싱 → 구조화 → 색인 → 시나리오 순서로 처리되고, 끝나면 비슷한 과거 사고와 반복된 규정이 연결됩니다.
              </Empty>
            </div>
          )}
          {route.name === "report" && <ReportView key={route.id} id={route.id} tab={route.tab} onChanged={refresh} />}
          {route.name === "search" && <SearchView key={route.q} q={route.q} />}
          {route.name === "stats" && <StatsView />}
          {route.name === "briefing" && <BriefingView />}
        </main>
      </div>
    </>
  );
}
