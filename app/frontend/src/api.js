// The ONLY place the API base URL lives. Set VITE_API_URL in a .env.local
// file (or in the build environment) to point at your deployed API.
// Unset: the dev server talks to a local API, and a production build talks to the server it is
// served from (FastAPI serves app/frontend/dist), so one deploy holds both.
const FROM_ENV = import.meta.env.VITE_API_URL
export const API_URL = (FROM_ENV !== undefined && FROM_ENV !== ''
  ? FROM_ENV
  : import.meta.env.DEV ? 'http://127.0.0.1:8000' : '').replace(/\/$/, '')

async function getJson(path, options) {
  const res = await fetch(`${API_URL}${path}`, options)
  if (!res.ok) throw new Error(`${path} returned HTTP ${res.status}`)
  return res.json()
}

/** GET / on the FastAPI demo. Returns {"message": "FastAPI is running!", "docs": "/docs"}. */
export function checkApi() {
  return getJson('/')
}

/** POST /sum?a=..&b=.. on the FastAPI demo. Returns {"result": a + b}. */
export function sumOnServer(a, b) {
  const q = new URLSearchParams({ a: String(a), b: String(b) })
  return getJson(`/sum?${q}`, { method: 'POST' })
}

// Where your own statistics endpoint slots in. The demo API has no SPC route,
// so App.jsx computes the limits in the browser with src/spc.js. Once your API
// has one (for example POST /spc/imr taking {"values": [...], "baseline_n": 20}),
// call it from App.jsx with this function. It must return the same shape that
// imrLimits() in src/spc.js returns:
//   { center, sigma, mrBar, ucl, lcl, baselineN }
export function limitsOnServer(values, baselineN) {
  return getJson('/spc/imr', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values, baseline_n: baselineN }),
  })
}

// Station map routes (docs/map-contract.md). Both return frames the map checks
// with validateFrame() in src/map/contract.js before drawing them.

/** POST /replay with the readings CSV and stations CSV. Returns {"frames": [Frame, ...]}. */
export function replayFromCsv(readingsFile, stationsFile) {
  const body = new FormData()
  body.append('readings', readingsFile)
  body.append('stations', stationsFile)
  return getJson('/replay', { method: 'POST', body })
}

/** GET /latest. Returns one Frame for the newest reading the server holds. */
export function fetchLatest() {
  return getJson('/latest')
}

// Dispatch console routes (app/app.py).

/** GET /datasets: [{id, name, interval_minutes, stations, docks, days: {week1, week2, event}}]. */
export function fetchDatasets() {
  return getJson('/datasets')
}

/** GET /frames/{scenario}?day=d&dataset=id: {"frames": [Frame per reading], "chart": {station_id: {xbar, sigma, lsl, usl}}}. */
// limits: 'rolling' (the charts use the last 7 clean days before this day) or 'week1' (fixed).
export function fetchFrames(scenario, day = 0, dataset = 'collegetown', limits = 'rolling') {
  return getJson(`/frames/${encodeURIComponent(scenario)}?day=${day}&dataset=${encodeURIComponent(dataset)}&limits=${encodeURIComponent(limits)}`)
}

/** GET /summary?dataset=id: night plan, rush slots, weekly p-charts and before/after counts. */
export function fetchSummary(dataset = 'collegetown') {
  return getJson(`/summary?dataset=${encodeURIComponent(dataset)}`)
}

