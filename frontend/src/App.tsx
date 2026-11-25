// 레이아웃: 상단 바 + (첫 화면: 랜딩) / (그 외: 왼쪽 올리기·검색·목록 + 오른쪽 화면). 화면은 주소 해시로 고른다 (route.ts).
import { useCallback, useEffect } from "react";
import { api, BUSY_STATES } from "./api/client";
import { call, useLoad } from "./api/call";
import Sidebar from "./components/Sidebar";
import TopNav from "./components/TopNav";
import { href, useRoute } from "./route";
import { useUpload } from "./useUpload";
import BriefingView from "./views/BriefingView";
import Landing from "./views/Landing";
import ReportView from "./views/ReportView";
import SearchView from "./views/SearchView";
import StatsView from "./views/StatsView";

const POLL_MS = 3000;

export default function App() {
  const route = useRoute();
  const [reports, reloadReports] = useLoad(() => call(api.GET("/api/reports")), []);
  const refresh = useCallback(() => void reloadReports(true), [reloadReports]);
  const uploader = useUpload(refresh);

  // 목록에 처리 중인 보고서가 있으면 3초마다 목록을 다시 불러온다 (상태 태그 갱신).
  const anyBusy = reports.state === "ok" && reports.data.some((r) => BUSY_STATES.includes(r.status.state));
  useEffect(() => {
    if (!anyBusy) return;
    const t = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(t);
  }, [anyBusy, refresh]);

  // 화면이 바뀌면 맨 위로
  useEffect(() => { window.scrollTo(0, 0); }, [route.name]);

  // "판단 훈련 시작": 처리가 끝난 가장 최근 보고서의 훈련 탭
  const firstDone = reports.state === "ok" ? reports.data.find((r) => r.status.state === "done") : undefined;
  const trainHref = firstDone ? href.report(firstDone.id, "train") : null;

  return (
    <>
      <TopNav route={route} trainHref={trainHref} uploading={uploader.busy} onUpload={(f) => void uploader.upload(f)} />
      {route.name === "home" ? (
        <Landing reports={reports} trainHref={trainHref} uploading={uploader.busy} notes={uploader.notes}
          onUpload={(f) => void uploader.upload(f)} onRetry={() => void reloadReports()} />
      ) : (
        <div className="wrap has-view">
          <Sidebar route={route} reports={reports} onUploaded={refresh} onRetry={() => void reloadReports()} />
          <main>
            {route.name === "report" && <ReportView key={route.id} id={route.id} tab={route.tab} onChanged={refresh} />}
            {route.name === "search" && <SearchView key={route.q} q={route.q} />}
            {route.name === "stats" && <StatsView />}
            {route.name === "briefing" && <BriefingView />}
          </main>
        </div>
      )}
    </>
  );
}
