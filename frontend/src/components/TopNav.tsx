// 상단 바: 로고 · 메뉴 · [PDF 올리기] [판단 훈련 시작]. 첫 화면에서는 파란 히어로 위에 투명하게 얹힌다.
import { href, type Route } from "../route";

export function RailMark({ size = 28 }: { size?: number }) {
  // 선로를 위에서 내려다본 모양 (침목 + 레일). 공식 로고가 아닌 서비스 표시.
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#ffffff" fillOpacity=".14" />
      <path d="M11 6 L8 26 M21 6 L24 26" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M10.4 10h11.2M9.8 14.5h12.4M9.1 19h13.8M8.5 23.5h15" stroke="var(--yellow)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

const LINKS = [
  { name: "home", label: "홈", to: "#/" },
  { name: "search", label: "유사사고 검색", to: href.search("") },
  { name: "stats", label: "반복 패턴", to: href.stats() },
  { name: "briefing", label: "작업 전 브리핑", to: href.briefing() },
] as const;

export default function TopNav({ route, trainHref, uploading, onUpload }: {
  route: Route;
  trainHref: string | null;
  uploading: boolean;
  onUpload: (files: FileList | null) => void;
}) {
  const overHero = route.name === "home";
  return (
    <header className={`topnav no-print ${overHero ? "over-hero" : ""}`}>
      <div className="topnav-in">
        <a className="brand" href="#/">
          <RailMark />
          <span className="brand-text">
            <b>사고사례 판단 훈련</b>
            <small>철도 사고조사보고서 기반 안전교육</small>
          </span>
        </a>
        <nav className="topnav-links" aria-label="주 메뉴">
          {LINKS.map((l) => (
            <a key={l.name} href={l.to} className={route.name === l.name ? "on" : ""}>{l.label}</a>
          ))}
        </nav>
        <div className="topnav-actions">
          <label className={`nbtn ghost ${uploading ? "disabled" : ""}`}>
            <input type="file" accept="application/pdf,.pdf" multiple disabled={uploading}
              onChange={(e) => { onUpload(e.target.files); e.target.value = ""; }} />
            {uploading ? "올리는 중…" : "PDF 올리기"}
          </label>
          {trainHref && <a className="nbtn solid" href={trainHref}>판단 훈련 시작</a>}
        </div>
      </div>
    </header>
  );
}
