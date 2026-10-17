// Station map page (the home page). Four data sources:
//   Simulation - GET /frames/{week1|week2|event}: the simulated days, with the van's stops
//   Sample - invented frames in src/map/sampleFrames.js, so the map works before the API exists
//   Upload - POST /replay with a readings CSV and a stations CSV, stepped through with the slider
//   Live   - GET /latest; the map changes once per new 15-min reading
// Every frame is checked against docs/map-contract.md before it is trusted.
// Under the map (src/dispatch/): the van on the map, the live feed, each station's charts and the
// weekly review. They only draw what the API sent. Run `npm run dev` and open /.
import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ActionList, StationMap } from './map/StationMap.jsx'
import { FRAMES as SAMPLE_FRAMES } from './map/sampleFrames.js'
import { validateFrame } from './map/contract.js'
import { bikesToMoveLabel, directionLabel, pct, READING_EVERY_MIN } from './map/stationMap.js'
import { API_URL, fetchFrames, fetchLatest, fetchSummary, replayFromCsv } from './api.js'
import { VanLayer, useVan } from './dispatch/VanLayer.jsx'
import { BikesChart, IChart, PChart } from './dispatch/charts.jsx'
import { clock, feedEntries, slotClock, stationStatus } from './dispatch/feed.js'
import './styles.css'
import './dispatch/dispatch.css'

// The feed has a new reading every 15 min. Live mode asks the server once a
// minute, so a new reading shows up within a minute of landing, but the map
// only changes when the reading time (as_of) changes.
const LIVE_CHECK_MS = 60_000
const STALE_AFTER_MIN = 2 * READING_EVERY_MIN // two readings missed
const SPEEDS = [[5000, '5 s'], [2000, '2 s'], [1000, '1 s'], [700, '0.7 s']] // one 15-min reading per step
const SCENARIOS = [['event', 'Event day'], ['week2', 'Week 2 · policy'], ['week1', 'Week 1 · no van']]
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function plusMinutes(asOf, min) {
  const t = Date.parse(asOf)
  if (Number.isNaN(t)) return null
  const d = new Date(t + min * 60_000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const SAMPLE_START = Math.max(0, SAMPLE_FRAMES.findIndex((f) => f.as_of.endsWith('T08:30')))

function minutesOld(asOf, now) {
  const t = Date.parse(asOf)
  return Number.isNaN(t) ? null : Math.round((now - t) / 60_000)
}

function Preview() {
  const [source, setSource] = useState('sim') // 'sim' | 'sample' | 'upload' | 'live'
  const [frames, setFrames] = useState([])
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [stepMs, setStepMs] = useState(5000)
  const [scenario, setScenario] = useState('event')
  const [day, setDay] = useState(0)
  const [chart, setChart] = useState(null) // control-chart centre and sigma per station, from the API
  const [summary, setSummary] = useState(null)
  const [pStation, setPStation] = useState(0)
  const [selectedId, setSelectedId] = useState(null)
  const [status, setStatus] = useState('') // what the API is doing, or why it failed
  const [files, setFiles] = useState({ readings: null, stations: null })
  const [now, setNow] = useState(Date.now())

  const frame = frames[Math.min(i, frames.length - 1)]
  const check = useMemo(() => (frame ? validateFrame(frame) : { ok: true, errors: [] }), [frame])
  const stations = frame?.stations ?? []
  const selected = stations.find((s) => s.station_id === selectedId)
  const van = useVan(frames, Math.min(i, Math.max(0, frames.length - 1)), playing && source !== 'live', stepMs)
  const feed = useMemo(() => (frames.length && 'trigger' in (frames[0].stations[0] ?? {}) ? feedEntries(frames, i) : []), [frames, i])
  const rush = summary?.rush_slots ?? []

  // Simulation: one day from the API
  useEffect(() => {
    if (source !== 'sim') return undefined
    let cancelled = false
    setStatus(`Loading ${scenario} from ${API_URL || 'this server'} ...`)
    fetchFrames(scenario, scenario === 'event' ? 0 : day)
      .then((res) => {
        if (cancelled) return
        setFrames(res.frames); setChart(res.chart); setI(0)
        setStatus(`Simulated ${res.date} from ${API_URL || 'this server'}/frames: one 15-min reading per step`)
      })
      .catch((err) => { if (!cancelled) setStatus(`Cannot reach ${API_URL || 'the API'}/frames (${err.message}). Is the API running?`) })
    return () => { cancelled = true }
  }, [source, scenario, day])

  useEffect(() => { fetchSummary().then(setSummary).catch(() => {}) }, [])

  // Replay animation (sample and upload only)
  useEffect(() => {
    if (!playing || source === 'live') return undefined
    const id = setInterval(() => setI((k) => (k + 1) % frames.length), stepMs)
    return () => clearInterval(id)
  }, [playing, source, frames.length, stepMs])

  // Live polling. On a failed call the last good frame stays on screen.
  useEffect(() => {
    if (source !== 'live') return undefined
    let cancelled = false
    const pull = async () => {
      try {
        const f = await fetchLatest()
        if (cancelled) return
        // same reading as on screen: keep it, so the map changes once per reading
        setFrames((old) => (old[0]?.as_of === f?.as_of ? old : [f]))
        setI(0)
        setStatus(`Live from ${API_URL}: a new reading every ${READING_EVERY_MIN} min`)
      } catch (err) {
        if (!cancelled) setStatus(`Cannot reach ${API_URL}/latest (${err.message}).`)
      }
      if (!cancelled) setNow(Date.now())
    }
    pull()
    const id = setInterval(pull, LIVE_CHECK_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [source])

  function choose(next) {
    setPlaying(next === 'sim')
    setSource(next)
    setStatus('')
    if (next !== 'sim') setChart(null)
    if (next === 'sim') { setFrames([]); setI(0) }
    if (next === 'sample') { setFrames(SAMPLE_FRAMES); setI(SAMPLE_START) }
    if (next === 'upload') { setFrames([]); setI(0) }
    if (next === 'live') { setFrames([]); setI(0); setStatus(`Connecting to ${API_URL}/latest ...`) }
  }

  async function upload(e) {
    e.preventDefault()
    if (!files.readings || !files.stations) { setStatus('Choose both CSV files first.'); return }
    setStatus('Uploading ...')
    try {
      const res = await replayFromCsv(files.readings, files.stations)
      if (!Array.isArray(res?.frames) || res.frames.length === 0) throw new Error('the reply has no frames')
      setFrames(res.frames)
      setChart(res.chart ?? null)
      setI(0)
      setStatus(`${res.frames.length} frames from ${API_URL || 'this server'}/replay`)
    } catch (err) {
      setStatus(`Upload failed: ${err.message}`)
    }
  }

  const age = source === 'live' && frame ? minutesOld(frame.as_of, now) : null

  return (
    <main className="map-page">
      <h1>Ithaca bikeshare: where to send the vans</h1>

      <div className="source" role="radiogroup" aria-label="Data source">
        {[['sim', 'Simulation'], ['sample', 'Sample'], ['upload', 'Upload CSV'], ['live', 'Live']].map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={source === k}
            className={source === k ? 'on' : ''} onClick={() => choose(k)}>{label}</button>
        ))}
      </div>

      {source === 'sim' && (
        <div className="d-sim">
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
          <p className="sample-note">Simulated data (data/README.md): 5 stations, 20 docks each, 100 bikes. The van goes when a
            station's control chart signals or it leaves 4-16 bikes.</p>
        </div>
      )}
      {source === 'sample' && (
        <p className="sample-note">Invented sample data for building the map, not real readings.</p>
      )}
      {source === 'upload' && (
        <form className="upload" onSubmit={upload}>
          <label>Readings CSV
            <input type="file" accept=".csv" onChange={(e) => setFiles((f) => ({ ...f, readings: e.target.files[0] ?? null }))} />
          </label>
          <label>Stations CSV
            <input type="file" accept=".csv" onChange={(e) => setFiles((f) => ({ ...f, stations: e.target.files[0] ?? null }))} />
          </label>
          <button type="submit">Analyze</button>
        </form>
      )}
      {status && (
        <p className="status">
          {status}
          {source === 'live' && status.startsWith('Cannot reach') &&
            (frame ? ' Showing the last reading received.' : ' No data yet; retrying every minute.')}
        </p>
      )}

      {!check.ok && (
        <div className="contract-error" role="alert">
          <strong>The back end sent data that breaks the map contract (docs/map-contract.md).</strong>
          {' '}Numbers for these stations may be wrong:
          <ul>{check.errors.slice(0, 8).map((m) => <li key={m}>{m}</li>)}</ul>
          {check.errors.length > 8 && <p>... and {check.errors.length - 8} more.</p>}
        </div>
      )}

      {frame && source !== 'live' && (
        <div className="replay">
          <button type="button" onClick={() => setPlaying((p) => !p)} disabled={frames.length < 2}>
            {playing ? 'Pause' : 'Play'}
          </button>
          <input type="range" min={0} max={frames.length - 1} value={i}
            onChange={(e) => setI(Number(e.target.value))} aria-label="Replay time" />
          <output>{frame.as_of.replace('T', ' ')}</output>
          <label className="d-speed">15 min =
            <select value={stepMs} onChange={(e) => setStepMs(Number(e.target.value))}>
              {SPEEDS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          {'reserve' in frame && <span className="d-reserve">Reserve depot: {frame.reserve} bikes{van.note ? ` · van ${van.note}` : ''}</span>}
        </div>
      )}
      {frame && source === 'live' && (
        <p className={age !== null && age > STALE_AFTER_MIN ? 'status stale' : 'status'}>
          Last reading {frame.as_of.replace('T', ' ')}
          {age !== null && age > STALE_AFTER_MIN
            ? ` (${age} min old: the feed may have stopped)`
            : plusMinutes(frame.as_of, READING_EVERY_MIN) && `, next reading due ${plusMinutes(frame.as_of, READING_EVERY_MIN)}`}
        </p>
      )}

      {frame && (
        <div className="map-grid">
          <StationMap stations={stations} selectedId={selectedId} onSelect={setSelectedId}>
            <VanLayer frames={frames} i={Math.min(i, frames.length - 1)} van={van} />
          </StationMap>
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
          <h2>Live feed <span>every station each 15 minutes, newest first</span></h2>
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
          <h2>Each station today <span>top: bikes, the 4-16 spec band, dashed expected path, ▲▼ van; bottom: control chart of net flow minus the usual, ±1/2/3σ, red = a rule fired</span></h2>
          <div className="d-stations">
            {stations.map((s) => {
              const st = stationStatus(frames, i, s.station_id)
              return (
                <div key={s.station_id} className="d-st">
                  <div className="d-sthead"><b>{s.station_id}</b> {s.name}</div>
                  <span className={`d-pill ${st.cls}`}>{st.text} · {s.bikes} bikes</span>
                  <BikesChart frames={frames} i={i} id={s.station_id} capacity={s.capacity} rush={rush}
                    policy={!(source === 'sim' && scenario === 'week1')} />
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
              <thead><tr><th>Station</th><th>Normal swing</th><th>Allowed start</th><th>06:00 start</th></tr></thead>
              <tbody>{summary.plan.map((p) => (
                <tr key={p.station_id}><td>{p.name}</td><td>{p.swing.toFixed(1)}</td>
                  <td>{p.lo.toFixed(1)} - {p.hi.toFixed(1)}</td><td><b>{p.start ?? 'none'}</b></td></tr>
              ))}</tbody>
            </table>
            <p className="status">A start s is allowed when 4 ≤ s + C(k) ≤ 16 all day (C = cumulative usual net flow); the plan is the middle.
              Rush slots: {rush.map(slotClock).join(', ') || 'none'}.</p>
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
