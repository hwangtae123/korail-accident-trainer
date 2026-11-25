// 첫 화면 그림: 아이소메트릭(30°) 선로 위의 열차 + 승강장의 보고서 더미. 상자 꼭짓점을 계산해 SVG 면으로 그린다.
import { useMemo } from "react";

type Shade = { top: string; right: string; left: string };
type Box = { x: number; y: number; z: number; w: number; d: number; h: number; c: Shade; cls?: string; ground?: boolean };

const U = 22; // 1칸 = 22px
const C30 = Math.cos(Math.PI / 6);
const proj = (x: number, y: number, z: number) => [(x - y) * C30 * U, (x + y) * 0.5 * U - z * U] as const;

const BALLAST: Shade = { top: "#2f6fd6", right: "#1f55b0", left: "#1a4896" };
const SLEEPER: Shade = { top: "#5d95ea", right: "#3f77cc", left: "#3567b6" };
const RAIL: Shade = { top: "#eaf4ff", right: "#a9cdf7", left: "#87b6ee" };
const BODY: Shade = { top: "#f4f9ff", right: "#c3defc", left: "#8fbdf3" };
const ROOF: Shade = { top: "#dcecff", right: "#a7ccf6", left: "#79abea" };
const GLASS: Shade = { top: "#123a7a", right: "#0d2f66", left: "#0d2f66" };
const STRIPE: Shade = { top: "#ffd560", right: "#ffc72c", left: "#e8ac00" };
const PLATFORM: Shade = { top: "#cfe5ff", right: "#93c1f5", left: "#6fa6ec" };
const PAPER: Shade = { top: "#ffffff", right: "#d7e8fd", left: "#b4d3f8" };
const PAPER_HL: Shade = { top: "#ffe08a", right: "#ffc72c", left: "#e8ac00" };

function scene(): Box[] {
  const b: Box[] = [];
  // 자갈 도상 + 승강장
  b.push({ x: -3, y: -0.7, z: -0.7, w: 19, d: 3.4, h: 0.55, c: BALLAST, ground: true });
  b.push({ x: 0, y: -4.2, z: -0.7, w: 9, d: 2.9, h: 1.1, c: PLATFORM, ground: true });
  // 침목
  for (let i = -3; i < 16; i += 1.1) b.push({ x: i, y: -0.35, z: -0.15, w: 0.45, d: 2.7, h: 0.15, c: SLEEPER, ground: true });
  // 레일 두 줄
  b.push({ x: -3, y: 0.2, z: 0, w: 19, d: 0.18, h: 0.18, c: RAIL, ground: true });
  b.push({ x: -3, y: 1.62, z: 0, w: 19, d: 0.18, h: 0.18, c: RAIL, ground: true });
  // 열차 3량 (차체 + 지붕 + 창문 띠 + 노란 띠)
  for (let k = 0; k < 3; k++) {
    const x = 0.6 + k * 4.25;
    b.push({ x, y: 0.05, z: 0.25, w: 3.95, d: 1.9, h: 1.35, c: BODY, cls: "iso-train" });
    b.push({ x: x + 0.2, y: 0.25, z: 1.6, w: 3.55, d: 1.5, h: 0.22, c: ROOF, cls: "iso-train" });
    b.push({ x: x + 0.45, y: 1.95, z: 0.95, w: 3.05, d: 0.02, h: 0.42, c: GLASS, cls: "iso-train" });
    b.push({ x: x + 0.05, y: 1.95, z: 0.52, w: 3.85, d: 0.02, h: 0.16, c: STRIPE, cls: "iso-train" });
  }
  // 승강장 위 보고서 더미 (얇은 판)
  for (let i = 0; i < 4; i++) {
    b.push({ x: 1.2 + i * 0.08, y: -3.6 + i * 0.05, z: 0.4 + i * 0.28, w: 2.6, d: 1.8, h: 0.2, c: i === 3 ? PAPER_HL : PAPER });
  }
  b.push({ x: 5.0, y: -3.4, z: 0.4, w: 1.6, d: 1.4, h: 0.55, c: PAPER });
  b.push({ x: 5.1, y: -3.3, z: 0.95, w: 1.4, d: 1.2, h: 0.18, c: PAPER });
  return b;
}

function faces(bx: Box) {
  const { x, y, z, w, d, h } = bx;
  const P = (a: number, b2: number, c: number) => proj(a, b2, c).map((v) => v.toFixed(1)).join(",");
  return {
    top: [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)].join(" "),
    right: [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)].join(" "),
    left: [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)].join(" "),
  };
}

export default function IsoTrain() {
  const { boxes, vb } = useMemo(() => {
    // 바닥(도상·승강장·침목·레일)을 먼저, 그 위 물체(열차·보고서)는 뒤에서 앞으로 (x+y가 클수록 앞)
    const depth = (a: Box) => (a.ground ? a.z * 100 : 1000) + a.x + a.w / 2 + a.y + a.d / 2 + a.z * 0.3; // 바닥은 낮은 층부터
    const all = scene().sort((a, b2) => depth(a) - depth(b2));
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const b2 of all) {
      for (const [px, py] of [proj(b2.x, b2.y + b2.d, b2.z), proj(b2.x + b2.w, b2.y, b2.z), proj(b2.x, b2.y, b2.z + b2.h), proj(b2.x + b2.w, b2.y + b2.d, b2.z)]) {
        minX = Math.min(minX, px); maxX = Math.max(maxX, px); minY = Math.min(minY, py); maxY = Math.max(maxY, py);
      }
    }
    const pad = 24;
    return { boxes: all, vb: [minX - pad, minY - pad, maxX - minX + pad * 2, maxY - minY + pad * 2] };
  }, []);

  return (
    <svg className="iso" viewBox={vb.map((v) => v.toFixed(0)).join(" ")} role="img"
      aria-label="선로 위를 달리는 열차와 승강장에 쌓인 사고조사보고서를 입체로 그린 그림">
      <defs>
        <radialGradient id="iso-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffd77a" stopOpacity=".75" />
          <stop offset="45%" stopColor="#ffc72c" stopOpacity=".25" />
          <stop offset="100%" stopColor="#ffc72c" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx={vb[0] + vb[2] * 0.52} cy={vb[1] + vb[3] * 0.78} rx={vb[2] * 0.46} ry={vb[3] * 0.2} fill="url(#iso-glow)" />
      {boxes.map((b2, i) => {
        const f = faces(b2);
        return (
          <g key={i} className={b2.cls}>
            <polygon points={f.left} fill={b2.c.left} />
            <polygon points={f.right} fill={b2.c.right} />
            <polygon points={f.top} fill={b2.c.top} />
          </g>
        );
      })}
    </svg>
  );
}
