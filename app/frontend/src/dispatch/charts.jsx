// Small SVG charts for the console. They only draw numbers the API sent (bikes, expected_bikes,
// x, trigger, the chart's xbar and sigma, the p-chart limits); nothing is computed here.

const W = 260

// Four time labels spread over the day, read from the frames themselves (any interval, any hours).
function axis(x, y0, frames) {
  const n = frames.length
  return [0, 1, 2, 3].map((q) => {
    const k = Math.round((q * (n - 1)) / 4)
    return <text key={q} x={x(k)} y={y0 + 13} textAnchor="middle">{frames[k]?.as_of.slice(11, 16)}</text>
  })
}

function Rush({ x, rush, top, bottom, slots }) {
  const w = (W - 28) / Math.max(1, slots - 1)
  return rush.map((k) => <rect key={k} className="c-rush" x={x(k) - w / 2} y={top} width={w} height={bottom - top} />)
}

const line = (pts) => pts.map(([px, py], n) => `${n ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join(' ')

// Bikes at one station so far today: spec band, expected path, the readings, van moves.
export function BikesChart({ frames, i, id, capacity = 20, rush = [], policy }) {
  const H = 118, L = 22, R = 6, T = 6, B = 18
  const SLOTS = frames.length
  const x = (k) => L + (k * (W - L - R)) / Math.max(1, SLOTS - 1)
  const y = (v) => T + (1 - v / capacity) * (H - T - B)
  const rows = frames.slice(0, i + 1).map((f) => f.stations.find((s) => s.station_id === id))
  const all = frames.map((f) => f.stations.find((s) => s.station_id === id))
  const LSL = all[0]?.lsl ?? 4
  const USL = all[0]?.usl ?? 16
  const path = []
  rows.forEach((s, k) => {
    path.push([x(k), y(s.bikes)])
    if (s.van_moved) path.push([x(k), y(s.bikes_after_van)])
  })
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Bikes at ${id} today`}>
      <Rush x={x} rush={rush} top={T} bottom={H - B} slots={SLOTS} />
      <rect className="c-band" x={L} y={y(USL)} width={W - L - R} height={y(LSL) - y(USL)} />
      {[0, LSL, USL, capacity].map((v) => <text key={v} x={L - 4} y={y(v) + 4} textAnchor="end">{v}</text>)}
      <line className="c-spec" x1={L} x2={W - R} y1={y(LSL)} y2={y(LSL)} />
      <line className="c-spec" x1={L} x2={W - R} y1={y(USL)} y2={y(USL)} />
      {policy && <path className="c-path" d={line(all.map((s, k) => [x(k), y(s.expected_bikes)]))} />}
      <path className="c-actual" d={line(path)} />
      {rows.map((s, k) => (s.bikes < LSL || s.bikes > USL) && <circle key={`o${k}`} className="c-pt oos" cx={x(k)} cy={y(s.bikes)} r="2.6" />)}
      {rows.map((s, k) => s.van_moved !== 0 && (
        <path key={`v${k}`} className="c-van"
          d={s.van_moved > 0
            ? `M${x(k) - 4},${y(s.bikes_after_van) + 8} L${x(k) + 4},${y(s.bikes_after_van) + 8} L${x(k)},${y(s.bikes_after_van) + 2} Z`
            : `M${x(k) - 4},${y(s.bikes_after_van) - 8} L${x(k) + 4},${y(s.bikes_after_van) - 8} L${x(k)},${y(s.bikes_after_van) - 2} Z`} />
      ))}
      <line className="c-now" x1={x(i)} x2={x(i)} y1={T} y2={H - B} />
      {axis(x, H - B, frames)}
    </svg>
  )
}

// I-chart of slot-adjusted net flow so far today, with 1, 2, 3 sigma zones; signals in red.
export function IChart({ frames, i, id, meta, rush = [] }) {
  const H = 112, L = 22, R = 26, T = 6, B = 18
  if (!meta || !(meta.sigma > 0)) return <p className="c-note">No chart: no variation in the history.</p>
  const SLOTS = frames.length
  // chart_x / chart_rule are the chart's own value and rule (rolling or week-1 limits, as the API
  // was asked); older frames without them fall back to x and the van's trigger.
  const pts = []
  for (let k = 1; k <= i && k < frames.length; k++) {
    const s = frames[k].stations.find((t) => t.station_id === id)
    const v = s?.chart_x ?? s?.x
    if (s && v != null) pts.push([k, { ...s, x: v, sigRule: s.chart_rule !== undefined ? s.chart_rule : (s.trigger?.startsWith('rule') ? s.trigger : null) }])
  }
  const span = Math.max(3.6 * meta.sigma, ...pts.map(([, s]) => Math.abs(s.x - meta.xbar) + 0.3))
  const x = (k) => L + (k * (W - L - R)) / Math.max(1, SLOTS - 1)
  const y = (v) => T + (1 - (v - meta.xbar + span) / (2 * span)) * (H - T - B)
  const zone = (z) => y(meta.xbar + z * meta.sigma)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Control chart at ${id}`}>
      <Rush x={x} rush={rush} top={T} bottom={H - B} slots={SLOTS} />
      {[1, 2, -1, -2].map((z) => <line key={z} className="c-zone" x1={L} x2={W - R} y1={zone(z)} y2={zone(z)} />)}
      {[3, -3].map((z) => <line key={z} className="c-lim" x1={L} x2={W - R} y1={zone(z)} y2={zone(z)} />)}
      <line className="c-cl" x1={L} x2={W - R} y1={zone(0)} y2={zone(0)} />
      <text x={W - R + 3} y={zone(3) + 4}>+3σ</text>
      <text x={W - R + 3} y={zone(-3) + 4}>−3σ</text>
      <text x={L - 4} y={zone(0) + 4} textAnchor="end">x̄</text>
      {pts.length > 1 && <path className="c-xline" d={line(pts.map(([k, s]) => [x(k), y(s.x)]))} />}
      {pts.map(([k, s]) => {
        const sig = s.sigRule
        return (
          <g key={k}>
            <circle className={sig ? 'c-pt sig' : 'c-pt'} cx={x(k)} cy={y(s.x)} r={sig ? 3.6 : 2}>
              <title>{`${frames[k].as_of.slice(11)}: x = ${s.x}${sig ? `, ${sig}` : ''}`}</title>
            </circle>
            {sig && <text className="c-sigtxt" x={x(k)} y={y(s.x) + (s.x > meta.xbar ? -6 : 13)} textAnchor="middle">R{sig.slice(5)}</text>}
          </g>
        )
      })}
      <line className="c-now" x1={x(i)} x2={x(i)} y1={T} y2={H - B} />
      {axis(x, H - B, frames)}
    </svg>
  )
}

// Weekly p-chart: week 1 (Phase I) sets pbar and the limits; week 2 days are judged against them.
export function PChart({ pc }) {
  const Wp = 560, H = 230, L = 38, R = 40, T = 12, B = 34
  const days = [...pc.phase1.map((d) => ({ ...d, phase: 1 })), ...pc.phase2.map((d) => ({ ...d, phase: 2 }))]
  const ymax = Math.max(pc.ucl ?? 0, ...days.map((d) => d.p)) * 1.12 + 0.02
  const x = (j) => L + ((j + 0.5) * (Wp - L - R)) / days.length
  const y = (v) => T + (1 - v / ymax) * (H - T - B)
  const ticks = []
  for (let v = 0; v <= ymax + 1e-9; v += 0.1) ticks.push(v)
  const dn = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
  const cls = (d) => (d.phase === 1 ? 'p1' : d.status === 'improved' ? 'good' : d.status === 'worse' ? 'sig' : '')
  return (
    <svg viewBox={`0 0 ${Wp} ${H}`} role="img" aria-label={`p-chart for ${pc.station_id}`}>
      {ticks.map((v) => (
        <g key={v}><line className="c-grid" x1={L} x2={Wp - R} y1={y(v)} y2={y(v)} />
          <text x={L - 6} y={y(v) + 4} textAnchor="end">{v.toFixed(1)}</text></g>
      ))}
      <line className="c-cl" x1={L} x2={Wp - R} y1={y(pc.pbar)} y2={y(pc.pbar)} />
      <text x={Wp - R + 4} y={y(pc.pbar) + 4}>p̄</text>
      <line className="c-lim" x1={L} x2={Wp - R} y1={y(pc.ucl)} y2={y(pc.ucl)} />
      <text x={Wp - R + 4} y={y(pc.ucl) + 4}>UCL</text>
      <line className="c-lim" x1={L} x2={Wp - R} y1={y(pc.lcl)} y2={y(pc.lcl)} />
      <text x={Wp - R + 4} y={y(pc.lcl) + 4}>LCL</text>
      <line className="c-grid" x1={x(pc.phase1.length - 0.5)} x2={x(pc.phase1.length - 0.5)} y1={T} y2={H - B} />
      <text x={x((pc.phase1.length - 1) / 2)} y={H - 4} textAnchor="middle">week 1 · Phase I</text>
      <text x={x(pc.phase1.length + (pc.phase2.length - 1) / 2)} y={H - 4} textAnchor="middle">week 2 · Phase II</text>
      {days.map((d, j) => (
        <g key={j}>
          <circle className={`c-pt ${cls(d)}`} cx={x(j)} cy={y(d.p)} r="4.5">
            <title>{`${d.phase === 1 ? 'Week 1' : 'Week 2'} ${dn[j % 7]}: ${d.d}/${pc.n ?? 64} = ${d.p.toFixed(3)} (${d.status})`}</title>
          </circle>
          <text x={x(j)} y={H - B + 14} textAnchor="middle">{dn[j % 7]}</text>
        </g>
      ))}
    </svg>
  )
}
