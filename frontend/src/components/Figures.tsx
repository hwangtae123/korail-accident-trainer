// 보고서 그림·사진: 사고 정보 탭의 갤러리(누르면 크게, ←/→로 넘김)와 판단 훈련 단계 옆에 붙는 그림.
import { useEffect, useState } from "react";
import { API_BASE, api, type Schemas } from "../api/client";
import { call, useLoad } from "../api/call";
import { PageLink } from "./common";

export type Fig = Schemas["FigureMeta"];
export const figSrc = (f: Fig) => `${API_BASE}${f.url}`;
const SOURCE = "출처: 항공·철도사고조사위원회 사고조사보고서";

export function useFigures(rid: string) {
  return useLoad(() => call(api.GET("/api/reports/{rid}/figures", { params: { path: { rid } } })), [rid]);
}

/** 판단 훈련 단계의 근거 쪽과 가장 가까운 그림 (같은 쪽 우선, 앞뒤 2쪽까지) */
export function figureNear(figs: Fig[], page?: number | null): Fig | undefined {
  if (!page) return undefined;
  return figs
    .filter((f) => Math.abs(f.page - page) <= 2)
    .sort((a, b) => Math.abs(a.page - page) - Math.abs(b.page - page) || (a.page > page ? 1 : -1))[0];
}

export function FigureGallery({ rid }: { rid: string }) {
  const [load] = useFigures(rid);
  const [open, setOpen] = useState<number | null>(null);
  if (load.state !== "ok" || load.data.length === 0) return null; // 그림이 없으면 카드를 감춘다
  const figs = load.data;
  return (
    <div className="card">
      <div className="row">
        <h3 className="first grow">사고 현장 사진·도면 <span className="meta">{figs.length}개</span></h3>
        <span className="meta">{SOURCE}</span>
      </div>
      <div className="fig-grid">
        {figs.map((f, i) => (
          <button key={f.n} className="fig-thumb" onClick={() => setOpen(i)} title={`${f.label} ${f.caption}`}>
            <img src={figSrc(f)} alt={`${f.label} ${f.caption}`} loading="lazy" width={f.width} height={f.height} />
            <span className="fig-cap"><b>{f.label}</b> {f.caption} <span className="meta">p.{f.page}</span></span>
          </button>
        ))}
      </div>
      {open !== null && <Lightbox rid={rid} figs={figs} index={open} onIndex={setOpen} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Lightbox({ rid, figs, index, onIndex, onClose }: {
  rid: string; figs: Fig[]; index: number; onIndex: (i: number) => void; onClose: () => void;
}) {
  const f = figs[index];
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onIndex((index + 1) % figs.length);
      if (e.key === "ArrowLeft") onIndex((index - 1 + figs.length) % figs.length);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [index, figs.length, onClose, onIndex]);
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={`${f.label} ${f.caption}`} onClick={onClose}>
      <div className="lb-in" onClick={(e) => e.stopPropagation()}>
        <img src={figSrc(f)} alt={`${f.label} ${f.caption}`} />
        <div className="lb-bar">
          <span className="grow"><b>{f.label}</b> {f.caption} <PageLink rid={rid} page={f.page} /></span>
          <span className="meta">{index + 1} / {figs.length}</span>
          <button className="btn sm" onClick={() => onIndex((index - 1 + figs.length) % figs.length)} aria-label="이전 그림">←</button>
          <button className="btn sm" onClick={() => onIndex((index + 1) % figs.length)} aria-label="다음 그림">→</button>
          <button className="btn sm" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}

/** 판단 훈련 단계 옆 그림 한 장 */
export function StepFigure({ rid, fig }: { rid: string; fig?: Fig }) {
  if (!fig) return null;
  return (
    <figure className="step-fig">
      <a href={figSrc(fig)} target="_blank" rel="noreferrer"><img src={figSrc(fig)} alt={`${fig.label} ${fig.caption}`} loading="lazy" /></a>
      <figcaption><b>{fig.label}</b> {fig.caption} <PageLink rid={rid} page={fig.page} /></figcaption>
    </figure>
  );
}
