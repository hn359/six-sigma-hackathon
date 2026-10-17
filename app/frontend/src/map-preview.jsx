// Station map page (the home page). One data source: the simulated cities from the API
// (GET /frames/{week1|week2|event}?dataset=...), replayed one reading per step.
// Every frame is checked against docs/map-contract.md before it is trusted.
// Under the map (src/dispatch/): the van on the map, the live feed, each station's charts and the
// weekly review. They only draw what the API sent. Run `npm run dev` and open /.
// (The API still has POST /replay for uploads and GET /latest; see /docs.)
import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ActionList } from './map/StationMap.jsx'
import Map3D from './dispatch/Map3D.jsx'
import { validateFrame } from './map/contract.js'
import { createSimulationState, publishSimulationState } from './map/sync.js'
import { bikesToMoveLabel, directionLabel, pct } from './map/stationMap.js'
import { API_URL, fetchDatasets, fetchFrames, fetchSummary } from './api.js'
import { useVan } from './dispatch/VanLayer.jsx'
import { BikesChart, IChart, PChart } from './dispatch/charts.jsx'
import { clock, feedEntries, stationStatus } from './dispatch/feed.js'
import './styles.css'
import './dispatch/dispatch.css'

const SPEEDS = [[5000, '5 s'], [2000, '2 s'], [1000, '1 s'], [700, '0.7 s']] // one reading per step
const SCENARIOS = [['event', 'Event day'], ['week2', 'Week 2 · policy'], ['week1', 'Week 1 · no van']]
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function Preview() {
  const [frames, setFrames] = useState([])
  const [frameContext, setFrameContext] = useState(null)
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [stepMs, setStepMs] = useState(5000)
  const [datasets, setDatasets] = useState([])
  // ?dataset=downtown in the address opens that city directly
  const [dataset, setDataset] = useState(() => new URLSearchParams(window.location.search).get('dataset') || 'collegetown')
  const [scenario, setScenario] = useState('event')
  const [day, setDay] = useState(0)
  const [chart, setChart] = useState(null) // control-chart centre and sigma per station, from the API
  const [summary, setSummary] = useState(null)
  const [pStation, setPStation] = useState(0)
  const [selectedId, setSelectedId] = useState(null)
  const [status, setStatus] = useState('') // what the API is doing, or why it failed

  const frame = frames[Math.min(i, frames.length - 1)]
  const check = useMemo(() => (frame ? validateFrame(frame) : { ok: true, errors: [] }), [frame])
  const stations = frame?.stations ?? []
  const selected = stations.find((s) => s.station_id === selectedId)
  const van = useVan(frames, Math.min(i, Math.max(0, frames.length - 1)), playing, stepMs)
  const feed = useMemo(() => (frames.length ? feedEntries(frames, i) : []), [frames, i])
  const rush = summary?.rush_slots ?? []
  const about = datasets.find((d) => d.id === dataset)

  // One simulated day from the API
  useEffect(() => {
    let cancelled = false
    setStatus(`Loading ${scenario} from ${API_URL || 'this server'} ...`)
    fetchFrames(scenario, scenario === 'event' ? 0 : day, dataset)
      .then((res) => {
        if (cancelled) return
        setFrames(res.frames); setFrameContext({ dataset, scenario, dayIndex: scenario === 'event' ? 0 : day, date: res.date })
        setChart(res.chart); setI(0); setSelectedId(null)
        setStatus(`Simulated ${res.date}: one reading every ${about?.interval_minutes ?? 15} min, replayed one per step`)
      })
      .catch((err) => { if (!cancelled) setStatus(`Cannot reach ${API_URL || 'the API'}/frames (${err.message}). Is the API running?`) })
    return () => { cancelled = true }
  }, [scenario, day, dataset, about?.interval_minutes])

  useEffect(() => { fetchDatasets().then(setDatasets).catch(() => {}) }, [])
  useEffect(() => { setSummary(null); setPStation(0); fetchSummary(dataset).then(setSummary).catch(() => {}) }, [dataset])

  // Replay clock
  useEffect(() => {
    if (!playing || frames.length < 2) return undefined
    const id = setInterval(() => setI((k) => (k + 1) % frames.length), stepMs)
    return () => clearInterval(id)
  }, [playing, frames.length, stepMs])

  // The combined BikeFlow page consumes this versioned message instead of scraping UI text.
  // A loading/error state deliberately carries no old frame, so changing city or scenario
  // cannot make the adjacent charts look current while this request is still in flight.
  useEffect(() => {
    const dayIndex = scenario === 'event' ? 0 : day
    const current = frame && frameContext?.dataset === dataset && frameContext?.scenario === scenario &&
      frameContext?.dayIndex === dayIndex && frameContext?.date === frame.as_of.slice(0, 10)
    const emit = () => {
      let state
      if (!current) {
        const failed = status.startsWith('Cannot reach')
        state = createSimulationState({ status: failed ? 'error' : 'loading', city:dataset, scenario,
          dayIndex, intervalMinutes:about?.interval_minutes ?? 15, reason:status })
      } else if (!check.ok) {
        state = createSimulationState({ status:'error', city:dataset, scenario, dayIndex,
          intervalMinutes:about?.interval_minutes ?? 15, reason:`Invalid simulation frame: ${check.errors[0]}` })
      } else {
        state = createSimulationState({ city:dataset, scenario, dayIndex,
          intervalMinutes:about?.interval_minutes ?? 15, asOf:frame.as_of, playing,
          reserve:frame.reserve,
          stations:frame.stations.map(({ station_id, bikes, capacity }) => ({ station_id, bikes, capacity })) })
      }
      publishSimulationState(state)
    }
    emit()
    const heartbeat = window.setInterval(emit, 1500)
    return () => window.clearInterval(heartbeat)
  }, [dataset, scenario, day, frame, frameContext, playing, status, check, about?.interval_minutes])

  return (
    <main className="map-page">
      <h1>Ithaca bikeshare: where to send the vans</h1>

      <div className="d-sim">
        <select value={dataset} onChange={(e) => { setDataset(e.target.value); setPlaying(true) }} aria-label="Simulated city">
          {(datasets.length ? datasets : [{ id: 'collegetown', name: 'Collegetown' }]).map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
        <div className="source" role="radiogroup" aria-label="Simulated day">
          {SCENARIOS.map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={scenario === k}
              className={scenario === k ? 'on' : ''} onClick={() => { setScenario(k); setPlaying(true) }}>{label}</button>
          ))}
        </div>
        {scenario !== 'event' && (
          <select value={day} onChange={(e) => { setDay(Number(e.target.value)); setPlaying(true) }} aria-label="Day of the week">
            {DAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
          </select>
        )}
        <p className="sample-note">Simulated data (data/README.md){about
          ? `: ${about.stations} stations, ${Math.min(...about.docks) === Math.max(...about.docks) ? `${about.docks[0]} docks each` : `${Math.min(...about.docks)}-${Math.max(...about.docks)} docks`}, ${about.fleet} bikes, a reading every ${about.interval_minutes} min`
          : ''}. The van goes when a station's control chart signals or it leaves 20%-80% of its docks.</p>
      </div>
      {status && <p className="status">{status}</p>}

      {!check.ok && (
        <div className="contract-error" role="alert">
          <strong>The back end sent data that breaks the map contract (docs/map-contract.md).</strong>
          {' '}Numbers for these stations may be wrong:
          <ul>{check.errors.slice(0, 8).map((m) => <li key={m}>{m}</li>)}</ul>
          {check.errors.length > 8 && <p>... and {check.errors.length - 8} more.</p>}
        </div>
      )}

      {frame && (
        <div className="replay">
          <button type="button" onClick={() => setPlaying((p) => !p)} disabled={frames.length < 2}>
            {playing ? 'Pause' : 'Play'}
          </button>
          <input type="range" min={0} max={frames.length - 1} value={i}
            onChange={(e) => setI(Number(e.target.value))} aria-label="Replay time" />
          <output>{frame.as_of.replace('T', ' ')}</output>
          <label className="d-speed">1 reading =
            <select value={stepMs} onChange={(e) => setStepMs(Number(e.target.value))}>
              {SPEEDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <span className="d-reserve">Reserve depot: {frame.reserve} bikes{van.note ? ` · van ${van.note}` : ''}</span>
        </div>
      )}

      {frame && (
        <div className="map-grid">
          <Map3D frames={frames} i={Math.min(i, frames.length - 1)} van={van}
            selectedId={selectedId} onSelect={setSelectedId} />
          <aside className="side">
            <h2>Stations</h2>
            <ActionList stations={stations} selectedId={selectedId} onSelect={setSelectedId} />
            {selected && (
              <div className="detail">
                <h3>{selected.name}</h3>
                <dl>
                  <dt>Bikes</dt><dd>{selected.bikes} of {selected.capacity}</dd>
                  <dt>Occupancy</dt><dd>{pct(selected.occupancy)}</dd>
                  <dt>Target</dt><dd>{pct(selected.target_occupancy)}</dd>
                  <dt>Status</dt><dd>{directionLabel(selected)}</dd>
                  <dt>Rule</dt><dd>{selected.rule ?? '—'}</dd>
                  {'trigger' in selected && <><dt>Trigger</dt><dd>{selected.trigger ?? 'none'}</dd></>}
                  {'expected_bikes' in selected && <><dt>Expected now</dt><dd>{selected.expected_bikes} bikes</dd></>}
                  {'x' in selected && <><dt>Chart x</dt><dd>{selected.x ?? '—'}</dd></>}
                  <dt>Bikes to move</dt><dd>{bikesToMoveLabel(selected.bikes_to_move)}</dd>
                  <dt>Availability</dt><dd>{pct(selected.availability)}</dd>
                </dl>
              </div>
            )}
          </aside>
        </div>
      )}

      {feed.length > 0 && (
        <section className="d-section">
          <h2>Live feed <span>every station at every reading, newest first</span></h2>
          <ul className="d-feed">
            {feed.map((e) => (
              <li key={e.asOf}>
                <div className="d-row"><span className="d-t">{clock(e.asOf)}</span>
                  {e.chips.map((c) => <span key={c.id} className={`d-chip ${c.cls}`}>{c.id} {c.bikes}</span>)}</div>
                {e.events.map((ev, n) => <div key={n} className={`d-ev ${ev.cls}`}>{ev.text}</div>)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {frame && chart && frames.length > 1 && (
        <section className="d-section">
          <h2>Each station today <span>top: bikes, the spec band (20%-80% of docks), dashed expected path, ▲▼ van; bottom: control chart of net flow minus the usual, ±1/2/3σ, red = a rule fired</span></h2>
          <div className="d-stations">
            {stations.map((s) => {
              const st = stationStatus(frames, i, s.station_id)
              return (
                <div key={s.station_id} className="d-st">
                  <div className="d-sthead"><b>{s.station_id}</b> {s.name}</div>
                  <span className={`d-pill ${st.cls}`}>{st.text} · {s.bikes} bikes</span>
                  <BikesChart frames={frames} i={i} id={s.station_id} capacity={s.capacity} rush={rush}
                    policy={scenario !== 'week1'} />
                  <IChart frames={frames} i={i} id={s.station_id} meta={chart[s.station_id]} rush={rush} />
                </div>
              )
            })}
          </div>
        </section>
      )}

      {summary && (
        <section className="d-section d-lower">
          <div>
            <h2>Night plan <span>learned from week 1</span></h2>
            <table className="d-table">
              <thead><tr><th>Station</th><th>Docks</th><th>Spec</th><th>Normal swing</th><th>Allowed start</th><th>Start</th></tr></thead>
              <tbody>{summary.plan.map((p) => (
                <tr key={p.station_id}><td>{p.name}</td><td>{p.capacity}</td><td>{p.lsl}-{p.usl}</td><td>{p.swing.toFixed(1)}</td>
                  <td>{p.lo.toFixed(1)} - {p.hi.toFixed(1)}</td><td><b>{p.start ?? 'none'}</b></td></tr>
              ))}</tbody>
            </table>
            <p className="status">A start s is allowed when LSL ≤ s + C(k) ≤ USL all day (C = cumulative usual net flow); the plan is the middle.
              Rush slots: {(summary.rush_times ?? []).join(', ') || 'none'}.</p>
            {summary.warnings?.map((w) => <p key={w} className="status stale">{w}</p>)}
          </div>
          <div>
            <h2>Did the policy work? <span>out-of-spec readings {summary.kpis.out_of_spec_week1} → {summary.kpis.out_of_spec_week2}</span></h2>
            <div className="source">
              {summary.pcharts.map((pc, n) => (
                <button key={pc.station_id} type="button" className={n === pStation ? 'on' : ''} onClick={() => setPStation(n)}>{pc.station_id}</button>
              ))}
            </div>
            <PChart pc={summary.pcharts[pStation]} />
            <p className="status">p-chart, one point per day: week 1 sets p̄ = {summary.pcharts[pStation].pbar.toFixed(3)},
              UCL = {summary.pcharts[pStation].ucl.toFixed(3)}, LCL = {summary.pcharts[pStation].lcl.toFixed(3)}; green week-2 days are
              below the LCL ({summary.pcharts[pStation].phase2.filter((d) => d.status === 'improved').length} of 7).</p>
          </div>
        </section>
      )}
    </main>
  )
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Preview />
  </React.StrictMode>,
)
