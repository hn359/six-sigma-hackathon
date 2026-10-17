// Map layers added to Jim's StationMap: the reserve depot, a bike count beside each station,
// and the van, which drives the route of the frame's van stop (frame.van from the API).
import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { Marker, Polyline, ScaleControl, useMap } from 'react-leaflet'
import { depotOf, stationStatus, vanHome, vanStops } from './feed.js'

const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
// Leaflet positions a marker with its own CSS transform, so the visible box is an inner element
// placed relative to a zero-size anchor at the exact map point (no transform on the outer div).
const icon = (cls, html, style = '') =>
  L.divIcon({ className: 'd-anchor', html: `<div class="${cls}" style="${style}">${html}</div>`, iconSize: [0, 0], iconAnchor: [0, 0] })
const shortName = (name) => name.replace(/\s*\(.*\)\s*$/, '')

function where(frame, id) {
  const depot = depotOf(frame.stations)
  if (id === 'depot') return [depot.lat, depot.lon]
  const s = frame.stations.find((t) => t.station_id === id)
  return s ? [s.lat, s.lon] : [depot.lat, depot.lon]
}

// Van position for frame i: while playing, drive this frame's route over most of one step.
export function useVan(frames, i, playing, stepMs) {
  const [van, setVan] = useState({ pos: [0, 0], route: null, note: null, arrived: true })
  const raf = useRef(0)
  const frame = frames[i]
  useEffect(() => {
    if (!frame) return undefined
    cancelAnimationFrame(raf.current)
    const stops = vanStops(frame.van)
    if (!stops.length || !playing || reduceMotion) {
      setVan({ pos: where(frame, vanHome(frames, i)), route: null, note: null, arrived: true })
      return undefined
    }
    const pts = [where(frame, vanHome(frames, i - 1)), ...stops.map((s) => where(frame, s))]
    const seg = pts.slice(1).map((p, n) => Math.hypot(p[0] - pts[n][0], p[1] - pts[n][1]))
    const total = seg.reduce((a, b) => a + b, 0) || 1
    const t0 = performance.now()
    const v = frame.van
    const step = (now) => {
      const t = Math.min(1, (now - t0) / (stepMs * 0.85))
      let d = t * total
      let n = 0
      while (n < seg.length - 1 && d > seg[n]) { d -= seg[n]; n++ }
      const u = seg[n] ? Math.min(1, d / seg[n]) : 1
      const pos = [pts[n][0] + (pts[n + 1][0] - pts[n][0]) * u, pts[n][1] + (pts[n + 1][1] - pts[n][1]) * u]
      const note = t >= 1 ? `${v.bikes_moved > 0 ? 'dropped' : 'took'} ${Math.abs(v.bikes_moved)} at ${v.station_id}`
        : n === 0 ? `to ${stops[0] === 'depot' ? 'depot' : stops[0]} for ${v.station_id}` : `carrying ${Math.abs(v.bikes_moved)}`
      setVan({ pos, route: pts, note, arrived: t >= 1 })
      if (t < 1) raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf.current)
  }, [frame, frames, i, playing, stepMs])
  return van
}

// Zoom the map to the stations (and the depot) whenever the set of stations changes,
// so they fill the map instead of sitting in a corner of the town.
function FitStations({ stations }) {
  const map = useMap()
  const key = stations.map((s) => `${s.station_id}:${s.lat},${s.lon}`).join('|')
  useEffect(() => {
    const pts = stations.filter((s) => Number.isFinite(s.lat) && Number.isFinite(s.lon)).map((s) => [s.lat, s.lon])
    if (pts.length < 2) return
    const depot = depotOf(stations)
    pts.push([depot.lat, depot.lon])
    map.fitBounds(pts, { paddingTopLeft: [70, 60], paddingBottomRight: [70, 110], maxZoom: 19 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key])
  return null
}

// Put inside <StationMap>. Frames without a van field (Jim's v1 samples) just get the counts.
export function VanLayer({ frames, i, van }) {
  const frame = frames[i]
  if (!frame) return null
  const hasVan = 'van' in frame
  const depot = depotOf(frame.stations)
  return (
    <>
      <FitStations stations={frame.stations} />
      <ScaleControl position="bottomleft" imperial={false} />
      {frame.stations.map((s) => {
        const st = stationStatus(frames, i, s.station_id)
        const shown = s.van_moved && van.arrived ? s.bikes_after_van : s.bikes
        const occ = Math.round((100 * shown) / s.capacity)
        const status = s.van_moved && van.arrived ? `${st.text} · was ${s.bikes}` : st.text
        return (
          <Marker key={`n${s.station_id}`} position={[s.lat, s.lon]} interactive={false}
            icon={icon(`d-pin ${st.cls}`,
              `<div class="halo" style="--h:${60 + 16 * (s.severity || 0)}px"></div>` +
              `<div class="ring"><span class="n">${shown}</span></div>` +
              `<div class="label"><b>${s.station_id}</b> ${shortName(s.name)}<small>${status}</small></div>`,
              `--occ:${occ}%`)} />
        )
      })}
      {hasVan && (
        <>
          <Marker position={[depot.lat, depot.lon]} interactive={false} icon={icon('d-depot', `DEPOT · ${frame.reserve ?? '?'}`)} />
          {van.route && <Polyline positions={van.route} pathOptions={{ className: 'd-route' }} />}
          <Marker position={van.pos} interactive={false} zIndexOffset={1000}
            icon={icon(van.route && !van.arrived ? 'd-van' : 'd-van parked', `VAN${van.note && !van.arrived ? `<small>${van.note}</small>` : ''}`)} />
        </>
      )}
    </>
  )
}
