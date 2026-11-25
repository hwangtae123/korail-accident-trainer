// PDF 올리기 (여러 개). 왼쪽 목록, 상단 바, 첫 화면이 같이 쓴다.
// 서버가 Supabase를 쓰면(GET /api/config direct_upload) PDF를 Storage에 직접 올린다:
//   SHA-1로 id 계산 -> POST /api/reports/upload-url -> 받은 주소로 PUT -> POST /api/reports/{id}/process (응답을 기다리지 않음)
// 서버리스(Vercel) 함수는 큰 요청 본문(약 4.5MB 초과)을 받지 못하기 때문이다. 아니면 기존처럼 POST /api/reports (multipart).
import { useState } from "react";
import { api, type Schemas } from "./api/client";
import { call } from "./api/call";
import { go, href } from "./route";

export type UploadNote = { name: string; text: string; kind: "ok" | "warn" | "bad"; id?: string };

let configPromise: Promise<Schemas["AppConfig"] | null> | null = null;
function getConfig() {
  configPromise ??= call(api.GET("/api/config")).then((r) => (r.ok ? r.data : null));
  return configPromise;
}

async function sha1Id(f: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-1", await f.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("").slice(0, 10);
}

async function uploadDirect(f: File, maxMb: number): Promise<UploadNote> {
  if (f.size > maxMb * 1024 * 1024) {
    return { name: f.name, text: `파일이 너무 큽니다 (${(f.size / 1048576).toFixed(1)}MB, 최대 ${maxMb}MB)`, kind: "bad" };
  }
  const head = new Uint8Array(await f.slice(0, 4).arrayBuffer());
  if (String.fromCharCode(...head) !== "%PDF") return { name: f.name, text: "PDF 파일이 아님 — 건너뜀", kind: "bad" };
  const id = await sha1Id(f);
  const r = await call(api.POST("/api/reports/upload-url", { body: { id, filename: f.name } }));
  if (!r.ok) return { name: f.name, text: r.message, kind: "bad" };
  if (!r.data.new || !r.data.upload_url) {
    return { name: f.name, text: "이미 있는 보고서입니다 — 기존 결과를 엽니다", kind: "warn", id };
  }
  try {
    const put = await fetch(r.data.upload_url, { method: "PUT", body: f, headers: { "Content-Type": "application/pdf" } });
    if (!put.ok) return { name: f.name, text: `저장소 업로드 실패 (HTTP ${put.status})`, kind: "bad", id };
  } catch (e) {
    return { name: f.name, text: `저장소 업로드 실패 — ${String(e)}`, kind: "bad", id };
  }
  // 처리는 1~2분 걸린다. 기다리지 않고 보고서 화면의 상태 폴링으로 진행을 본다.
  void call(api.POST("/api/reports/{rid}/process", { params: { path: { rid: id } }, body: { filename: f.name } }));
  return { name: f.name, text: "접수됨 — 처리 시작 (1~2분)", kind: "ok", id };
}

async function uploadMultipart(f: File): Promise<UploadNote> {
  const r = await call(api.POST("/api/reports", {
    body: { file: f as unknown as string },
    bodySerializer: () => {
      const fd = new FormData();
      fd.append("file", f);
      return fd;
    },
  }));
  if (!r.ok) return { name: f.name, text: r.message, kind: "bad" };
  if (r.data.new) return { name: f.name, text: "접수됨 — 처리 시작", kind: "ok", id: r.data.id };
  return { name: f.name, text: "이미 있는 보고서입니다 — 기존 결과를 엽니다", kind: "warn", id: r.data.id };
}

export function useUpload(onUploaded: () => void) {
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<UploadNote[]>([]);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    const cfg = await getConfig();
    const out: UploadNote[] = [];
    for (const f of Array.from(files)) {
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        out.push({ name: f.name, text: "PDF 파일이 아님 — 건너뜀", kind: "bad" });
        continue;
      }
      out.push(cfg?.direct_upload ? await uploadDirect(f, cfg.max_upload_mb) : await uploadMultipart(f));
    }
    setNotes(out);
    setBusy(false);
    onUploaded();
    const first = out.find((n) => n.id && n.kind !== "bad");
    if (first?.id) go(href.report(first.id));
  }

  return { busy, notes, upload, clear: () => setNotes([]) };
}
