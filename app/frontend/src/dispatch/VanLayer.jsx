// Map layers added to Jim's StationMap: the reserve depot, a bike count beside each station,
// and the van, which drives the route of the frame's van stop (frame.van from the API).
import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { Marker, Polyline } from 'react-leaflet'
import { DEPOT, stationStatus, vanHome, vanStops } from './feed.js'

const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const icon = (cls, html) => L.divIcon({ className: cls, html, iconSize: null })

function where(frame, id) {
  if (id === 'depot') return [DEPOT.lat, DEPOT.lon]
  const s = frame.stations.find((t) => t.station_id === id)
  return s ? [s.lat, s.lon] : [DEPOT.lat, DEPOT.lon]
}

// Van position for frame i: while playing, drive this frame's route over most of one step.
export function useVan(frames, i, playing, stepMs) {
  const [van, setVan] = useState({ pos: [DEPOT.lat, DEPOT.lon], route: null, note: null, arrived: true })
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

// Put inside <StationMap>. Frames without a van field (Jim's v1 samples) just get the counts.
export function VanLayer({ frames, i, van }) {
  const frame = frames[i]
  if (!frame) return null
  const hasVan = 'van' in frame
  return (
    <>
      {frame.stations.map((s) => {
        const st = stationStatus(frames, i, s.station_id)
        const after = s.van_moved && van.arrived ? ` → ${s.bikes_after_van}` : ''
        return (
          <Marker key={`n${s.station_id}`} position={[s.lat, s.lon]} interactive={false}
            icon={icon(`d-count ${st.cls}`, `${s.bikes}${after}<small>${st.text}</small>`)} />
        )
      })}
      {hasVan && (
        <>
          <Marker position={[DEPOT.lat, DEPOT.lon]} interactive={false} icon={icon('d-depot', `DEPOT · ${frame.reserve ?? '?'}`)} />
          {van.route && <Polyline positions={van.route} pathOptions={{ className: 'd-route' }} />}
          <Marker position={van.pos} interactive={false} zIndexOffset={1000}
            icon={icon('d-van', `VAN${van.note && !van.arrived ? `<small>${van.note}</small>` : ''}`)} />
        </>
      )}
    </>
  )
}
