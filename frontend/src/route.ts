// 주소창 해시로 화면을 고른다 (라이브러리 없이). 새로고침·뒤로 가기·링크 공유가 된다.
//   #/                 처음 화면
//   #/r/<id>           보고서 사고 정보     #/r/<id>/train  판단 훈련     #/r/<id>/edit  시나리오 편집
//   #/search?q=...     유사사고 검색        #/stats         반복 패턴     #/briefing     작업 전 브리핑
import { useEffect, useState } from "react";

export type Route =
  | { name: "home" }
  | { name: "report"; id: string; tab: "info" | "train" | "edit" }
  | { name: "search"; q: string }
  | { name: "stats" }
  | { name: "briefing" };

export function parseRoute(hash: string): Route {
  const h = hash.replace(/^#/, "") || "/";
  const [path, query = ""] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "r" && parts[1]) {
    const tab = parts[2] === "train" ? "train" : parts[2] === "edit" ? "edit" : "info";
    return { name: "report", id: decodeURIComponent(parts[1]), tab };
  }
  if (parts[0] === "search") return { name: "search", q: new URLSearchParams(query).get("q") ?? "" };
  if (parts[0] === "stats") return { name: "stats" };
  if (parts[0] === "briefing") return { name: "briefing" };
  return { name: "home" };
}

export const href = {
  report: (id: string, tab: "info" | "train" | "edit" = "info") =>
    `#/r/${encodeURIComponent(id)}${tab === "info" ? "" : `/${tab}`}`,
  search: (q: string) => `#/search?${new URLSearchParams({ q })}`,
  stats: () => "#/stats",
  briefing: () => "#/briefing",
};

export const go = (h: string) => {
  window.location.hash = h;
};

export function useRoute(): Route {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const f = () => setHash(window.location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return parseRoute(hash);
}
