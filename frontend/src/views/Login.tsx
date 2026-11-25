// 로그인 화면 + 잠금. 서버에 ACCESS_PASSWORD가 있으면 비밀번호를 넣어야 화면이 열린다 (30일 유지).
// /api/login, /api/session은 계약(openapi)에 없는 API라 fetch로 직접 부른다.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { API_BASE } from "../api/client";
import { RailMark } from "../components/TopNav";

export const AUTH_REQUIRED = "auth:required"; // call.ts가 401을 받으면 보내는 이벤트

type Gate = "checking" | "locked" | "open";

export default function LoginGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<Gate>("checking");

  useEffect(() => {
    fetch(`${API_BASE}/api/session`)
      .then((r) => (r.ok ? r.json() : { ok: true })) // 오래된 서버(이 API 없음)면 잠금 없이 연다
      .then((s: { ok: boolean }) => setGate(s.ok ? "open" : "locked"))
      .catch(() => setGate("open")); // 서버 연결 오류는 각 화면이 알아서 보여 준다
    const lock = () => setGate("locked");
    window.addEventListener(AUTH_REQUIRED, lock);
    return () => window.removeEventListener(AUTH_REQUIRED, lock);
  }, []);

  if (gate === "checking") return null;
  if (gate === "locked") return <Login onOk={() => setGate("open")} />;
  return <>{children}</>;
}

function Login({ onOk }: { onOk: () => void }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!pw || busy) return;
    setBusy(true);
    setErr("");
    try {
      const r = await fetch(`${API_BASE}/api/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pw }),
      });
      if (r.ok) return onOk();
      setErr(r.status === 401 ? "비밀번호가 맞지 않습니다" : `서버 오류 (HTTP ${r.status})`);
      setPw("");
    } catch {
      setErr("서버에 연결할 수 없습니다");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <div className="hero-grid" />
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <RailMark size={40} />
          <div>
            <b>사고사례 판단 훈련</b>
            <small>철도 사고조사보고서 기반 교육</small>
          </div>
        </div>
        <label htmlFor="login-pw">비밀번호</label>
        <input id="login-pw" className="input" type="password" inputMode="numeric" autoComplete="current-password"
          autoFocus value={pw} onChange={(e) => setPw(e.target.value)} placeholder="비밀번호를 입력하세요" />
        {err && <p className="login-err" role="alert">{err}</p>}
        <button className="btn primary" type="submit" disabled={!pw || busy}>{busy ? "확인 중…" : "들어가기"}</button>
      </form>
    </div>
  );
}
