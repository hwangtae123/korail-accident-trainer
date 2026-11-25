// API 호출 결과를 화면에서 다루기 쉬운 모양으로 바꾼다: 성공 / 501(준비 중) / 오류(메시지) / 네트워크 오류.
import { useCallback, useEffect, useRef, useState } from "react";

export type Result<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; status: number; message: string };

type Fetched<T> = { data?: T; error?: unknown; response: Response };

function errorMessage(status: number, error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422: [{loc, msg}, ...]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`)
      .join("; ");
  }
  if (status === 404) return "찾을 수 없습니다";
  if (status === 501) return "준비 중인 기능입니다";
  return `서버 오류 (HTTP ${status})`;
}

const NO_BACKEND = "백엔드 서버가 연결되지 않았습니다 — 배포 설정의 VITE_API_BASE(백엔드 주소)를 확인하세요";

export async function call<T>(p: Promise<Fetched<T>>): Promise<Result<T>> {
  try {
    const { data, error, response } = await p;
    if (response.ok) return { ok: true, data: data as T, status: response.status };
    // 로그인이 풀렸으면(쿠키 만료·비밀번호 변경) 로그인 화면으로 (views/Login.tsx)
    if (response.status === 401) window.dispatchEvent(new Event("auth:required"));
    // 우리 백엔드(FastAPI)는 오류도 JSON으로 준다. JSON이 아니면(정적 호스팅의 404 등) 백엔드 주소가 설정되지 않은 것이다 (예: Vercel에 화면만 배포)
    if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
      return { ok: false, status: 0, message: NO_BACKEND };
    }
    return { ok: false, status: response.status, message: errorMessage(response.status, error) };
  } catch (e) {
    const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
    const hint = local ? "backend가 8000번에 떠 있는지 확인" : "백엔드 주소(VITE_API_BASE)와 서버 상태 확인";
    return { ok: false, status: 0, message: `서버에 연결할 수 없습니다 (${hint}) — ${String(e)}` };
  }
}

export type Load<T> =
  | { state: "loading" }
  | { state: "ok"; data: T }
  | { state: "error"; status: number; message: string };

/** 화면이 열릴 때(그리고 deps가 바뀔 때) 불러오고, reload()로 다시 부른다. silent reload는 로딩 표시 없이 갱신. */
export function useLoad<T>(fn: () => Promise<Result<T>>, deps: unknown[]) {
  const [load, setLoad] = useState<Load<T>>({ state: "loading" });
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async (silent = false) => {
    const my = ++seq.current;
    if (!silent) setLoad({ state: "loading" });
    const r = await fnRef.current();
    if (my !== seq.current) return; // 더 늦게 시작한 요청이 있으면 버린다
    setLoad(r.ok ? { state: "ok", data: r.data } : { state: "error", status: r.status, message: r.message });
  }, []);

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return [load, reload] as const;
}
