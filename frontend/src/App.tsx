// 스캐폴드용 임시 화면: 백엔드 연결과 타입이 동작하는지만 보여준다.
// 실제 화면은 docs/ui-spec.md와 docs/backlog.md(FE-*)를 따라 frontend-dev가 만든다.
import { useEffect, useState } from "react";
import { api, type ReportSummary } from "./api/client";

export default function App() {
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.GET("/api/reports").then(({ data, error }) => {
      if (error) setError(String(error));
      else setReports(data ?? []);
    }).catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24 }}>
      <h1>사고사례 판단 훈련</h1>
      {error && <p>백엔드 연결 실패: {error} (backend에서 uvicorn이 8000번으로 떠 있는지 확인)</p>}
      {reports && <p>보고서 {reports.length}건 연결됨</p>}
    </main>
  );
}
