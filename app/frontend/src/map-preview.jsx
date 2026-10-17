// Station map page. Three data sources:
//   Sample - invented frames in src/map/sampleFrames.js, so the map works before the API exists
//   Upload - POST /replay with a readings CSV and a stations CSV, stepped through with the slider
//   Live   - GET /latest; the map changes once per new 15-min reading
// Every frame is checked against docs/map-contract.md before it is trusted.
// Run `npm run dev` and open /map.html.
import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ActionList, StationMap } from './map/StationMap.jsx'
import { FRAMES as SAMPLE_FRAMES } from './map/sampleFrames.js'
import { validateFrame } from './map/contract.js'
import { bikesToMoveLabel, directionLabel, pct, READING_EVERY_MIN } from './map/stationMap.js'
import { API_URL, fetchLatest, replayFromCsv } from './api.js'
import './styles.css'

// The feed has a new reading every 15 min. Live mode asks the server once a
// minute, so a new reading shows up within a minute of landing, but the map
// only changes when the reading time (as_of) changes.
const LIVE_CHECK_MS = 60_000
const STALE_AFTER_MIN = 2 * READING_EVERY_MIN // two readings missed
const PLAY_STEP_MS = 700 // replay speed: one 15-min reading per step

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
  const [source, setSource] = useState('sample') // 'sample' | 'upload' | 'live'
  const [frames, setFrames] = useState(SAMPLE_FRAMES)
  const [i, setI] = useState(SAMPLE_START) // 08:30 in the sample, mid morning rush
  const [playing, setPlaying] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [status, setStatus] = useState('') // what the API is doing, or why it failed
  const [files, setFiles] = useState({ readings: null, stations: null })
  const [now, setNow] = useState(Date.now())

  const frame = frames[Math.min(i, frames.length - 1)]
  const check = useMemo(() => (frame ? validateFrame(frame) : { ok: true, errors: [] }), [frame])
  const stations = frame?.stations ?? []
  const selected = stations.find((s) => s.station_id === selectedId)

  // Replay animation (sample and upload only)
  useEffect(() => {
    if (!playing || source === 'live') return undefined
    const id = setInterval(() => setI((k) => (k + 1) % frames.length), PLAY_STEP_MS)
    return () => clearInterval(id)
  }, [playing, source, frames.length])

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
    setPlaying(false)
    setSource(next)
    setStatus('')
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
      setI(0)
      setStatus(`${res.frames.length} frames from ${API_URL}/replay`)
    } catch (err) {
      setStatus(`Upload failed: ${err.message}`)
    }
  }

  const age = source === 'live' && frame ? minutesOld(frame.as_of, now) : null

  return (
    <main className="map-page">
      <h1>Ithaca bikeshare: where to send the vans</h1>

      <div className="source" role="radiogroup" aria-label="Data source">
        {[['sample', 'Sample'], ['upload', 'Upload CSV'], ['live', 'Live']].map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={source === k}
            className={source === k ? 'on' : ''} onClick={() => choose(k)}>{label}</button>
        ))}
      </div>

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
          <StationMap stations={stations} selectedId={selectedId} onSelect={setSelectedId} />
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
                  <dt>Bikes to move</dt><dd>{bikesToMoveLabel(selected.bikes_to_move)}</dd>
                  <dt>Availability</dt><dd>{pct(selected.availability)}</dd>
                </dl>
              </div>
            )}
          </aside>
        </div>
      )}
    </main>
  )
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Preview />
  </React.StrictMode>,
)
