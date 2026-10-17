// Pure helpers for the station map. No statistics here: direction, severity and
// bikes_to_move arrive already computed from the API (app/qc.py). This file only
// decides how a station is drawn and in what order the dispatcher sees it.

export const ITHACA_CENTER = [42.4445, -76.4943]
export const ITHACA_ZOOM = 14

// The station feed is read every 15 minutes; one frame = one reading time.
export const READING_EVERY_MIN = 15

export const COLORS = {
  empty: '#e5484d', // red: too few bikes, nothing to rent
  full: '#6f88fc',  // periwinkle: too many bikes, nowhere to return
  ok: '#12b8da',    // cyan: in control (Fairy palette)
}

// severity: 0 in control, 1 eight in a row on one side, 2 two of three beyond
// 2 sigma, 3 one point beyond 3 sigma.
export const SEVERITY_LABELS = ['in control', 'sustained drift', 'building', 'act now']

export function markerStyle(station) {
  const sev = clampSeverity(station.severity)
  const dir = sev === 0 ? 'ok' : station.direction
  const color = COLORS[dir] ?? COLORS.ok
  return {
    radius: 7 + 4 * sev,
    color,
    fillColor: color,
    fillOpacity: sev === 0 ? 0.7 : 0.85,
    weight: 1,
  }
}

export function clampSeverity(sev) {
  const n = Number(sev)
  if (!Number.isFinite(n)) return 0
  return Math.max(0, Math.min(3, Math.round(n)))
}

export function directionLabel(station) {
  if (clampSeverity(station.severity) === 0) return 'in control'
  if (station.direction === 'empty') return 'too empty'
  if (station.direction === 'full') return 'too full'
  return 'in control'
}

// "add 6" means bring 6 bikes, "remove 4" means take 4 away, "—" means no move
// (in-control stations get null from the back end on purpose).
export function bikesToMoveLabel(n) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return '—'
  const v = Math.round(Number(n))
  if (v === 0) return '—'
  return v > 0 ? `add ${v}` : `remove ${Math.abs(v)}`
}

// The station list: every station, drifting ones first (most severe, then the
// largest gap from normal), in-control ones after, then by station id so the
// order never flickers between frames.
export function rankStations(stations) {
  return stations
    .slice()
    .sort(
      (a, b) =>
        clampSeverity(b.severity) - clampSeverity(a.severity) ||
        Math.abs(b.gap ?? 0) - Math.abs(a.gap ?? 0) ||
        String(a.station_id).localeCompare(String(b.station_id)),
    )
}

// Stations without usable coordinates are listed, not silently dropped.
export function splitPlaceable(stations) {
  const placed = []
  const missing = []
  for (const s of stations) {
    const ok =
      Number.isFinite(s.lat) && Number.isFinite(s.lon) &&
      Math.abs(s.lat) <= 90 && Math.abs(s.lon) <= 180
    ;(ok ? placed : missing).push(s)
  }
  // draw calm stations first so severe ones sit on top
  placed.sort((a, b) => clampSeverity(a.severity) - clampSeverity(b.severity))
  return { placed, missing }
}

export function pct(x) {
  return Number.isFinite(x) ? `${Math.round(x * 100)}%` : '—'
}
