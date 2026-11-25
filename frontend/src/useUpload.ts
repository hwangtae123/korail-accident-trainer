// PDF 올리기 (여러 개). 왼쪽 목록, 상단 바, 첫 화면이 같이 쓴다.
import { useState } from "react";
import { api } from "./api/client";
import { call } from "./api/call";
import { go, href } from "./route";

export type UploadNote = { name: string; text: string; kind: "ok" | "warn" | "bad"; id?: string };

export function useUpload(onUploaded: () => void) {
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<UploadNote[]>([]);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    const out: UploadNote[] = [];
    for (const f of Array.from(files)) {
      if (!f.name.toLowerCase().endsWith(".pdf")) {
        out.push({ name: f.name, text: "PDF 파일이 아님 — 건너뜀", kind: "bad" });
        continue;
      }
      const r = await call(api.POST("/api/reports", {
        body: { file: f as unknown as string },
        bodySerializer: () => {
          const fd = new FormData();
          fd.append("file", f);
          return fd;
        },
      }));
      if (!r.ok) out.push({ name: f.name, text: r.message, kind: "bad" });
      else if (r.data.new) out.push({ name: f.name, text: "접수됨 — 처리 시작", kind: "ok", id: r.data.id });
      else out.push({ name: f.name, text: "이미 있는 보고서입니다 — 기존 결과를 엽니다", kind: "warn", id: r.data.id });
    }
    setNotes(out);
    setBusy(false);
    onUploaded();
    const first = out.find((n) => n.id);
    if (first?.id) go(href.report(first.id));
  }

  return { busy, notes, upload, clear: () => setNotes([]) };
}
