import { COLORS, markerStyle, seriesRange, stationSeries } from './stationMap.js'

// One chart per full-width row, so the drawing is wide and short.
const W = 1000
const H = 190
const PAD = { l: 40, r: 40, t: 10, b: 22 }

const hhmm = (asOf) => asOf.slice(11, 16)

// One station's control chart: the value the back end charts, its centre line
// and its limits, up to the replay's current reading. Points outside the
// limits are drawn large in the station's drift colour. Nothing is computed
// here; every number comes from the frames.
export function StationChart({ frames, upto, station, selected, onSelect }) {
  const points = stationSeries(frames, upto, station.station_id)
  const range = seriesRange(frames, station.station_id)
  const t0 = Date.parse(frames[0].as_of)
  const t1 = Date.parse(frames[frames.length - 1].as_of)

  const x = (asOf) => PAD.l + (W - PAD.l - PAD.r) * (t1 > t0 ? (Date.parse(asOf) - t0) / (t1 - t0) : 0.5)
  const y = (v) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - range.lo) / (range.hi - range.lo))
  const line = (key) => points.map((p) => `${x(p.as_of).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ')
  const now = points[points.length - 1]

  // an hour mark every 2 hours between the first and last reading
  const ticks = []
  const first = new Date(t0)
  first.setMinutes(0, 0, 0)
  for (let t = first.getTime(); t <= t1; t += 2 * 3_600_000) {
    if (t >= t0) ticks.push(t)
  }
  const xt = (t) => PAD.l + (W - PAD.l - PAD.r) * (t1 > t0 ? (t - t0) / (t1 - t0) : 0.5)

  return (
    <figure className={selected ? 'chart sel' : 'chart'}>
      <figcaption>
        <button type="button" onClick={() => onSelect?.(station.station_id)}>
          <span className="dot" style={{ background: markerStyle(station).color }} />
          {station.name}
        </button>
      </figcaption>
      {!range || points.length === 0 ? (
        <p className="chart-none">No chart data from the back end for this station.</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} role="img"
          aria-label={`Control chart for ${station.name}: ${points.length} readings, ${points.filter((p) => p.severity === 3).length} outside the limits`}>
          <polyline className="c-limit" points={line('ucl')} />
          <polyline className="c-center" points={line('center')} />
          <polyline className="c-limit" points={line('lcl')} />
          <text className="c-lab" x={x(now.as_of) + 4} y={y(now.ucl) + 4}>UCL</text>
          <text className="c-lab" x={x(now.as_of) + 4} y={y(now.center) + 4}>CL</text>
          <text className="c-lab" x={x(now.as_of) + 4} y={y(now.lcl) + 4}>LCL</text>
          <polyline className="c-series" points={line('value')} />
          {points.map((p) => {
            const out = p.severity === 3
            const col = p.severity === 0 ? COLORS.ok : COLORS[p.direction] ?? COLORS.ok
            return <circle key={p.as_of} cx={x(p.as_of)} cy={y(p.value)} r={out ? 3.5 : 2} fill={col} />
          })}
          <line className="c-now" x1={x(now.as_of)} x2={x(now.as_of)} y1={PAD.t} y2={H - PAD.b} />
          {ticks.map((t) => {
            const d = new Date(t)
            return (
              <text key={t} className="c-lab" x={xt(t)} y={H - 6} textAnchor="middle">
                {`${String(d.getHours()).padStart(2, '0')}:00`}
              </text>
            )
          })}
          <text className="c-lab" x={2} y={y(range.hi) + 10}>{range.hi.toFixed(2)}</text>
          <text className="c-lab" x={2} y={y(range.lo)}>{range.lo.toFixed(2)}</text>
        </svg>
      )}
    </figure>
  )
}

// All stations' charts, in station-id order so they never jump around.
export function ChartGrid({ frames, upto, selectedId, onSelect, chartOf }) {
  const current = frames[Math.min(upto, frames.length - 1)]
  const stations = current.stations.slice().sort((a, b) => String(a.station_id).localeCompare(String(b.station_id)))
  return (
    <section className="charts">
      <h2>Control chart for each station</h2>
      <p className="chart-of">Charted value: {chartOf || 'as sent by the back end'}. Centre line and 3-sigma limits from the back end; the grey line marks the current reading.</p>
      <div className="chart-grid">
        {stations.map((s) => (
          <StationChart key={s.station_id} frames={frames} upto={upto} station={s}
            selected={s.station_id === selectedId} onSelect={onSelect} />
        ))}
      </div>
    </section>
  )
}
