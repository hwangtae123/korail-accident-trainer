// 시나리오 편집 (FE-4): 도입·역할·단계(상황, 질문, 선택지 추가/삭제, 정답, 해설, 근거 규정, 실제 결과) -> PUT 저장.
import { useState } from "react";
import { api, type Scenario } from "../api/client";
import { call, useLoad } from "../api/call";
import { ErrorBox, Loaded } from "../components/common";
import { go, href } from "../route";

type Step = Scenario["steps"][number];

const LETTERS = "ABCDEFGHIJ";
const nextId = (ids: string[]) => [...LETTERS].find((c) => !ids.includes(c)) ?? `O${ids.length + 1}`;

const blankStep = (): Step => ({
  situation: "", question: "", options: [{ id: "A", text: "" }, { id: "B", text: "" }], answer_id: "A",
  explanation: "", rule_refs: [], what_happened: "", evidence: { page: null, quote: "", verified: null },
});

export default function ScenarioEditor({ id }: { id: string }) {
  const [load, reload] = useLoad(
    () => call(api.GET("/api/reports/{rid}/scenario", { params: { path: { rid: id } } })), [id]);
  return (
    <div className="card">
      <Loaded load={load} what="시나리오" onRetry={() => void reload()}>
        {(sc) => <Form id={id} initial={sc} />}
      </Loaded>
    </div>
  );
}

function Form({ id, initial }: { id: string; initial: Scenario }) {
  const [sc, setSc] = useState<Scenario>(() => structuredClone(initial));
  const [saving, setSaving] = useState(false);
  const [notReady, setNotReady] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const set = (patch: Partial<Scenario>) => { setSc((s) => ({ ...s, ...patch })); setSaved(false); };
  const setStep = (i: number, patch: Partial<Step>) =>
    set({ steps: sc.steps.map((s, k) => (k === i ? { ...s, ...patch } : s)) });

  const problems = sc.steps.flatMap((s, i) => {
    const out: string[] = [];
    if (!s.options.some((o) => o.id === s.answer_id)) out.push(`${i + 1}단계: 정답을 고르세요`);
    if (s.options.length < 2) out.push(`${i + 1}단계: 선택지가 2개 이상 필요합니다`);
    if (s.options.some((o) => !o.text.trim())) out.push(`${i + 1}단계: 빈 선택지가 있습니다`);
    return out;
  });

  async function save() {
    setSaving(true);
    setErr(null);
    const r = await call(api.PUT("/api/reports/{rid}/scenario", { params: { path: { rid: id } }, body: sc }));
    setSaving(false);
    if (r.ok) { setSc(r.data); setSaved(true); return; }
    if (r.status === 501) setNotReady(true);
    else setErr(r.message);
  }

  return (
    <div className="editor">
      <div className="row">
        <h2 className="grow">시나리오 편집</h2>
        <a className="btn sm" href={href.report(id, "train")}>편집 취소</a>
      </div>
      <div className="banner">저장하면 검수 상태가 "검수 전"으로 돌아갑니다. 저장한 뒤 내용을 확인하고 다시 "검수 완료 표시"를 눌러 주세요.</div>

      <label className="field">제목<input className="input" value={sc.title} onChange={(e) => set({ title: e.target.value })} /></label>
      <label className="field">교육생 역할<input className="input" value={sc.role} onChange={(e) => set({ role: e.target.value })} /></label>
      <label className="field">도입 상황<textarea className="input" rows={3} value={sc.intro} onChange={(e) => set({ intro: e.target.value })} /></label>

      {sc.steps.map((s, i) => (
        <fieldset key={i} className="step">
          <legend>판단 지점 {i + 1}</legend>
          <div className="row right">
            <button className="btn sm" disabled={i === 0}
              onClick={() => { const a = [...sc.steps]; [a[i - 1], a[i]] = [a[i], a[i - 1]]; set({ steps: a }); }}>위로</button>
            <button className="btn sm danger"
              onClick={() => window.confirm(`판단 지점 ${i + 1}을 삭제할까요?`) && set({ steps: sc.steps.filter((_, k) => k !== i) })}>
              단계 삭제
            </button>
          </div>
          <label className="field">상황<textarea className="input" rows={3} value={s.situation} onChange={(e) => setStep(i, { situation: e.target.value })} /></label>
          <label className="field">질문<input className="input" value={s.question} onChange={(e) => setStep(i, { question: e.target.value })} /></label>
          <div className="field">선택지 (정답에 표시)
            {s.options.map((o, k) => (
              <div key={o.id} className="row opt-edit">
                <input type="radio" name={`ans-${i}`} checked={s.answer_id === o.id} onChange={() => setStep(i, { answer_id: o.id })} title="정답" />
                <b>{o.id}</b>
                <input className="input grow" value={o.text}
                  onChange={(e) => setStep(i, { options: s.options.map((x, j) => (j === k ? { ...x, text: e.target.value } : x)) })} />
                <button className="btn sm" disabled={s.options.length <= 2}
                  onClick={() => setStep(i, { options: s.options.filter((_, j) => j !== k) })}>삭제</button>
              </div>
            ))}
            <button className="btn sm" onClick={() => setStep(i, { options: [...s.options, { id: nextId(s.options.map((o) => o.id)), text: "" }] })}>
              선택지 추가
            </button>
          </div>
          <label className="field">해설 (올바른 판단과 이유)<textarea className="input" rows={3} value={s.explanation} onChange={(e) => setStep(i, { explanation: e.target.value })} /></label>
          <label className="field">근거 규정 (쉼표로 구분)
            <input className="input" value={(s.rule_refs ?? []).join(", ")}
              onChange={(e) => setStep(i, { rule_refs: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
          </label>
          <label className="field">실제 사고에서는<textarea className="input" rows={3} value={s.what_happened} onChange={(e) => setStep(i, { what_happened: e.target.value })} /></label>
          {s.evidence?.page && <div className="meta">근거 쪽: p.{s.evidence.page} {s.evidence.quote && `“${s.evidence.quote}”`}</div>}
        </fieldset>
      ))}
      <button className="btn" onClick={() => set({ steps: [...sc.steps, blankStep()] })}>판단 지점 추가</button>

      <label className="field">마무리 (사고원인과 교훈)<textarea className="input" rows={4} value={sc.debrief} onChange={(e) => set({ debrief: e.target.value })} /></label>

      {problems.length > 0 && <ul className="problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {err && <ErrorBox message={err} />}
      {notReady && <div className="banner warn"><b>준비 중</b> 시나리오 저장 기능이 아직 서버에 없습니다 (HTTP 501).</div>}
      <div className="row mt">
        <button className="btn primary" disabled={saving || notReady || problems.length > 0} onClick={() => void save()}>
          {saving ? "저장 중…" : "저장"}
        </button>
        {saved && <><span className="tag ok">저장됨 (검수 전)</span>
          <button className="btn sm" onClick={() => go(href.report(id, "train"))}>훈련 화면으로</button></>}
      </div>
    </div>
  );
}
