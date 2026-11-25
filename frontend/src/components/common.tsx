// 여러 화면이 같이 쓰는 작은 조각들: 근거 링크, 확인 표시, 상태 태그, 로딩·오류·준비 중 상자.
import type { ReactNode } from "react";
import { pdfUrl, type ReportStatus, type Schemas } from "../api/client";
import type { Load } from "../api/call";

type Evidence = Schemas["Evidence"];

export const STATE_LABEL: Record<ReportStatus["state"], string> = {
  queued: "대기",
  parsing: "파싱",
  extracting: "구조화",
  indexing: "색인",
  scenario: "시나리오",
  done: "완료",
  error: "오류",
  ocr_needed: "OCR 필요",
};

export function StatusTag({ state }: { state: ReportStatus["state"] }) {
  const cls = state === "done" ? "ok" : state === "error" ? "bad" : state === "ocr_needed" ? "warn" : "busy";
  return <span className={`tag ${cls}`}>{STATE_LABEL[state]}</span>;
}

/** 원문 PDF 해당 쪽 링크 (새 탭) */
export function PageLink({ rid, page }: { rid: string; page?: number | null }) {
  if (!page) return null;
  return (
    <a className="pg" href={pdfUrl(rid, page)} target="_blank" rel="noreferrer" title="원문 PDF의 이 쪽 열기">
      p.{page}
    </a>
  );
}

export function Verified({ v }: { v?: boolean | null }) {
  if (v === true) return <span className="vf ok" title="원문 구절을 코드로 대조해 찾음">✓ 원문 확인</span>;
  if (v === false) return <span className="vf bad" title="이 쪽 원문에서 구절을 찾지 못함 — 직접 확인 필요">⚠ 원문에서 못 찾음</span>;
  return null;
}

/** 항목 끝에 붙는 근거: p.N + 확인 표시 + 원문 구절 */
export function EvidenceLine({ rid, ev }: { rid: string; ev?: Evidence | null }) {
  if (!ev || (!ev.page && !ev.quote)) return null;
  return (
    <>
      <PageLink rid={rid} page={ev.page} />
      <Verified v={ev.verified} />
      {ev.quote && <span className="q">“{ev.quote}”</span>}
    </>
  );
}

export function LlmNotice({ children }: { children?: ReactNode }) {
  return <div className="notice">{children ?? "LLM이 작성한 내용입니다. 원문과 대조하세요."}</div>;
}

export function Loading({ text = "불러오는 중…" }: { text?: string }) {
  return <div className="empty"><span className="spin" /> {text}</div>;
}

export function NotReady({ what }: { what: string }) {
  return (
    <div className="empty">
      <span className="tag warn">준비 중</span> {what}은(는) 아직 서버에 구현되지 않았습니다 (HTTP 501).
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="errbox">
      <b>오류</b> {message}
      {onRetry && <button className="btn sm" onClick={onRetry}>다시 시도</button>}
    </div>
  );
}

/** Load 상태에 따라 로딩·501·오류를 보여 주고, 성공이면 children(data)를 그린다. */
export function Loaded<T>({ load, what, onRetry, children }: {
  load: Load<T>;
  what: string;
  onRetry?: () => void;
  children: (data: T) => ReactNode;
}) {
  if (load.state === "loading") return <Loading />;
  if (load.state === "error") {
    if (load.status === 501) return <NotReady what={what} />;
    return <ErrorBox message={load.message} onRetry={onRetry} />;
  }
  return <>{children(load.data)}</>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n) + "…" : s);

/** LLM 답변용 아주 작은 Markdown 표시: 제목(#), 목록(- · *, 1.), **굵게**. HTML은 해석하지 않는다(글자 그대로). */
export function Md({ text }: { text: string }) {
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part);
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const h = line.match(/^#{1,6}\s+(.*)$/);
    const ul = line.match(/^\s*[-*·•]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const ordered = !!ol;
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push((ul ?? ol)![1]);
      continue;
    }
    flush();
    if (h) blocks.push(<h4 key={blocks.length}>{inline(h[1])}</h4>);
    else if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="md">{blocks}</div>;
}
