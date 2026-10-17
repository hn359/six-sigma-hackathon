// 3D dispatch map (MapLibre GL, OpenFreeMap vector tiles: free, no API key).
// Each station is a glass column as tall as its docks, filled up to its bikes and coloured by
// status, with white rings at the spec limits (LSL, USL). Ground halo = severity. The van drives
// its route. Nothing is computed here: bikes, limits, triggers and the van stop come from the API.
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { depotOf, stationStatus } from './feed.js'
import { makeModelLayer } from './scene3d.js'
import { hourOf, paletteAt } from './daylight.js'

const SRC = 'https://tiles.openfreemap.org/planet'
const FONT = ['Noto Sans Regular']
const PITCH = 58
const BEARING = -24
const COLOR = { ok: '#3ddc84', back: '#3ddc84', sig: '#ff4d4d', oos: '#ffb020', fix: '#4da3ff' }

const STYLE = {
  version: 8,
  transition: { duration: 0, delay: 0 },   // colour changes (time of day) apply at once
  glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
  sources: { omt: { type: 'vector', url: SRC } },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#07090c' } },
    { id: 'landcover', type: 'fill', source: 'omt', 'source-layer': 'landcover', paint: { 'fill-color': '#0c1610', 'fill-opacity': 0.7 } },
    { id: 'park', type: 'fill', source: 'omt', 'source-layer': 'park', paint: { 'fill-color': '#0d1c13', 'fill-opacity': 0.9 } },
    { id: 'water', type: 'fill', source: 'omt', 'source-layer': 'water', paint: { 'fill-color': '#0b2133' } },
    { id: 'road-minor', type: 'line', source: 'omt', 'source-layer': 'transportation',
      filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'track']]],
      paint: { 'line-color': '#1f2730', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 1, 18, 7] } },
    { id: 'road-path', type: 'line', source: 'omt', 'source-layer': 'transportation',
      filter: ['in', ['get', 'class'], ['literal', ['path', 'pedestrian']]],
      paint: { 'line-color': '#1a2129', 'line-width': 1.2, 'line-dasharray': [2, 2] } },
    { id: 'road-major', type: 'line', source: 'omt', 'source-layer': 'transportation',
      filter: ['in', ['get', 'class'], ['literal', ['primary', 'secondary', 'tertiary', 'trunk', 'motorway']]],
      paint: { 'line-color': '#2b3642', 'line-width': ['interpolate', ['linear'], ['zoom'], 14, 2, 18, 12] } },
    { id: 'buildings', type: 'fill-extrusion', source: 'omt', 'source-layer': 'building', minzoom: 14,
      paint: {
        'fill-extrusion-color': '#161c23',
        'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8],
        'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
        'fill-extrusion-opacity': 0.88,
      } },
    { id: 'road-names', type: 'symbol', source: 'omt', 'source-layer': 'transportation_name', minzoom: 15,
      layout: { 'symbol-placement': 'line', 'text-field': ['get', 'name'], 'text-font': FONT, 'text-size': 11 },
      paint: { 'text-color': '#6f7c89', 'text-halo-color': '#07090c', 'text-halo-width': 1.4 } },
  ],
}

// a circle polygon (lon/lat ring) of radius r metres
function disc(lon, lat, r, n = 40) {
  const dLat = r / 111320
  const dLon = r / (111320 * Math.cos((lat * Math.PI) / 180))
  const ring = []
  for (let j = 0; j <= n; j++) {
    const a = (2 * Math.PI * j) / n
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)])
  }
  return [ring]
}

// ground halos (severity) and a dashed ring round the selected station; the stations and the van
// themselves are three.js models (scene3d.js)
function stationFeatures(frames, i, selectedId) {
  const f = frames[i]
  const feats = []
  for (const s of f.stations) {
    const st = stationStatus(frames, i, s.station_id)
    const p = { station_id: s.station_id, color: COLOR[st.cls] ?? COLOR.ok }
    feats.push({ type: 'Feature', properties: { ...p, kind: 'halo' },
      geometry: { type: 'Polygon', coordinates: disc(s.lon, s.lat, 95 + 22 * (s.severity || 0)) } })
    if (s.station_id === selectedId) {
      feats.push({ type: 'Feature', properties: { ...p, kind: 'sel' },
        geometry: { type: 'Polygon', coordinates: disc(s.lon, s.lat, 105) } })
    }
  }
  return { type: 'FeatureCollection', features: feats }
}

// MapLibre positions a marker with classes on its element, so the styled box is an inner div
// that we restyle freely; the outer element is never touched after creation.
const tag = (cls, html) => {
  const el = document.createElement('div')
  const inner = document.createElement('div')
  inner.className = cls
  inner.innerHTML = html
  el.appendChild(inner)
  return el
}
const setTag = (marker, cls, html) => {
  const inner = marker.getElement().firstChild
  if (cls !== null) inner.className = cls
  inner.innerHTML = html
}

export default function Map3D({ frames, i, van, selectedId, onSelect, nextTrips = [], playing = false, stepMs = 5000 }) {
  const box = useRef(null)
  const map = useRef(null)
  const ready = useRef(false)
  const markers = useRef({})
  const fitKey = useRef('')
  const models = useRef(null)
  if (!models.current) models.current = makeModelLayer()
  const lastVan = useRef(null)
  const lastHour = useRef(null)
  const [phase, setPhase] = useState('')
  const latest = useRef({ frames, i, van, selectedId })
  const [is3d, setIs3d] = useState(true)
  latest.current = { frames, i, van, selectedId }

  // create the map once
  useEffect(() => {
    const m = new maplibregl.Map({
      container: box.current, style: STYLE, center: [-76.485, 42.442], zoom: 16,
      pitch: PITCH, bearing: BEARING, attributionControl: false, maxPitch: 75,
    })
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    m.addControl(new maplibregl.AttributionControl({ compact: true }))   // the tiles carry their own credits
    // draw the stations as soon as the style is ready; do not wait for every map tile
    const setup = () => {
      if (m.getSource('stn')) return
      m.addSource('stn', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addSource('route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      m.addLayer({ id: 'stn-halo', type: 'fill', source: 'stn', filter: ['==', ['get', 'kind'], 'halo'],
        paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.18 } })
      m.addLayer({ id: 'route', type: 'line', source: 'route',
        paint: { 'line-color': '#ffd23f', 'line-width': 4, 'line-dasharray': [2, 1.5], 'line-opacity': 0.95 } })
      m.addLayer({ id: 'stn-sel', type: 'line', source: 'stn', filter: ['==', ['get', 'kind'], 'sel'],
        paint: { 'line-color': '#f2f5f7', 'line-width': 2, 'line-dasharray': [2, 2] } })
      m.addLayer(models.current.layer)     // the 3D stations and van (three.js)
      for (const id of ['stn-halo']) {
        m.on('click', id, (e) => onSelect?.(e.features?.[0]?.properties?.station_id))
        m.on('mouseenter', id, () => { m.getCanvas().style.cursor = 'pointer' })
        m.on('mouseleave', id, () => { m.getCanvas().style.cursor = '' })
      }
      ready.current = true
      draw()
    }
    m.on('style.load', setup)
    m.on('load', setup)
    if (m.isStyleLoaded()) setup()
    map.current = m
    return () => { ready.current = false; m.remove() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function draw() {
    const m = map.current
    const { frames: fr, i: k, van: v, selectedId: sel } = latest.current
    if (!m || !ready.current || !fr.length) return
    const f = fr[Math.min(k, fr.length - 1)]
    // colours follow the time of day of the reading on screen
    const hour = hourOf(f.as_of)
    if (hour !== lastHour.current) {
      lastHour.current = hour
      const pal = paletteAt(hour)
      m.setPaintProperty('bg', 'background-color', pal.bg)
      m.setPaintProperty('landcover', 'fill-color', pal.land)
      m.setPaintProperty('park', 'fill-color', pal.park)
      m.setPaintProperty('water', 'fill-color', pal.water)
      m.setPaintProperty('road-minor', 'line-color', pal.minor)
      m.setPaintProperty('road-path', 'line-color', pal.minor)
      m.setPaintProperty('road-major', 'line-color', pal.major)
      m.setPaintProperty('buildings', 'fill-extrusion-color', pal.building)
      m.setPaintProperty('road-names', 'text-color', pal.label)
      m.setPaintProperty('road-names', 'text-halo-color', pal.bg)
      models.current.setLight(pal.sun, pal.sunI, pal.amb)
      box.current.style.background = pal.bg
      setPhase(`${f.as_of.slice(11, 16)} · ${pal.phase}`)
    }
    m.getSource('stn').setData(stationFeatures(fr, Math.min(k, fr.length - 1), sel))
    m.getSource('route').setData(v.route
      ? { type: 'Feature', geometry: { type: 'LineString', coordinates: v.route.map(([la, lo]) => [lo, la]) } }
      : { type: 'FeatureCollection', features: [] })

    // labels, depot and van as HTML markers (they stay readable when the map is tilted)
    const seen = new Set()
    for (const s of f.stations) {
      seen.add(s.station_id)
      const st = stationStatus(fr, Math.min(k, fr.length - 1), s.station_id)
      const shown = s.van_moved && v.arrived ? s.bikes_after_van : s.bikes
      const html = `<b>${s.station_id}</b> ${s.name.replace(/\s*\(.*\)\s*$/, '')}` +
        `<span class="n">${shown}<i>/${s.capacity}</i></span><small>${st.text}</small>`
      let mk = markers.current[s.station_id]
      if (!mk) {
        const el = tag(`m3-tag ${st.cls}`, html)
        el.addEventListener('click', () => latest.current.onSelect?.(s.station_id))
        mk = markers.current[s.station_id] = new maplibregl.Marker({ element: el, anchor: 'top', offset: [0, 26] })
          .setLngLat([s.lon, s.lat]).addTo(m)
      } else {
        mk.setLngLat([s.lon, s.lat])
        setTag(mk, `m3-tag ${st.cls}${s.station_id === sel ? ' sel' : ''}`, html)
      }
    }
    for (const id of Object.keys(markers.current)) {
      if (!seen.has(id) && !id.startsWith('_')) { markers.current[id].remove(); delete markers.current[id] }
    }
    const depot = depotOf(f.stations)
    const dhtml = `DEPOT · ${f.reserve ?? '?'}`
    if (!markers.current._depot) {
      markers.current._depot = new maplibregl.Marker({ element: tag('m3-depot', dhtml) }).setLngLat([depot.lon, depot.lat]).addTo(m)
    } else { markers.current._depot.setLngLat([depot.lon, depot.lat]); setTag(markers.current._depot, null, dhtml) }
    const moving = v.route && !v.arrived
    const vpos = Number.isFinite(v.pos?.[0]) && v.pos[0] !== 0 ? [v.pos[1], v.pos[0]] : [depot.lon, depot.lat]
    // heading from the last position: radians, 0 = east, counter-clockwise (three.js Y rotation)
    let heading = lastVan.current?.heading ?? 0
    if (lastVan.current) {
      const de = (vpos[0] - lastVan.current.lon) * Math.cos((vpos[1] * Math.PI) / 180)
      const dn = vpos[1] - lastVan.current.lat
      if (Math.hypot(de, dn) > 1e-7) heading = Math.atan2(dn, de)
    }
    lastVan.current = { lon: vpos[0], lat: vpos[1], heading }
    const vhtml = moving && v.note ? v.note : ''
    if (!markers.current._van) {
      markers.current._van = new maplibregl.Marker({ element: tag(vhtml ? 'm3-van' : 'm3-van hidden', vhtml), anchor: 'bottom', offset: [0, -40] })
        .setLngLat(vpos).addTo(m)
    } else {
      markers.current._van.setLngLat(vpos)
      setTag(markers.current._van, vhtml ? 'm3-van' : 'm3-van hidden', vhtml)
    }
    models.current.update(
      f.stations.map((s) => ({
        id: s.station_id, lon: s.lon, lat: s.lat, capacity: s.capacity,
        bikes: s.van_moved && v.arrived ? s.bikes_after_van : s.bikes,
        cls: stationStatus(fr, Math.min(k, fr.length - 1), s.station_id).cls,
      })),
      { lon: vpos[0], lat: vpos[1], heading, visible: 'van' in f },
    )

    // zoom to the network when the set of stations changes
    const key = f.stations.map((s) => s.station_id).join('|')
    if (key !== fitKey.current) {
      fitKey.current = key
      const b = new maplibregl.LngLatBounds()
      f.stations.forEach((s) => b.extend([s.lon, s.lat]))
      b.extend([depot.lon, depot.lat])
      m.fitBounds(b, { padding: { top: 60, bottom: 150, left: 70, right: 70 }, maxZoom: 18.6, duration: 0, pitch: is3dRef.current ? PITCH : 0, bearing: is3dRef.current ? BEARING : 0 })
    }
  }

  const is3dRef = useRef(true)

  // cyclists: while reading i is on screen, the riders of the next interval ride between stations
  const rodeFor = useRef('')
  useEffect(() => {
    const m = models.current
    const f = frames[i]
    if (!f) return
    const key = `${f.as_of}|${frames.length}`
    if (!playing) { m.clearRiders(); rodeFor.current = ''; return }
    if (rodeFor.current === key) return
    rodeFor.current = key
    const byId = Object.fromEntries(f.stations.map((s) => [s.station_id, s]))
    m.ride(nextTrips, byId, stepMs)
  }, [frames, i, playing, stepMs, nextTrips])
  latest.current.onSelect = onSelect
  useEffect(() => { draw() })

  function toggle3d() {
    const next = !is3d
    setIs3d(next)
    is3dRef.current = next
    const m = map.current
    if (!m) return
    m.easeTo({ pitch: next ? PITCH : 0, bearing: next ? BEARING : 0, duration: 900 })
    m.setLayoutProperty('buildings', 'visibility', next ? 'visible' : 'none')
  }

  return (
    <div className="m3-wrap">
      <div ref={box} className="m3-map" />
      <div className="m3-tools">
        <button type="button" onClick={toggle3d}>{is3d ? '2D view' : '3D view'}</button>
        {phase && <span className="m3-phase">{phase}</span>}
        <button type="button" onClick={() => map.current?.easeTo({ bearing: (map.current.getBearing() + 90) % 360, duration: 900 })}>Rotate</button>
      </div>
      <ul className="m3-legend" aria-label="Map legend">
        <li><span className="dot" style={{ background: COLOR.ok }} /> in control</li>
        <li><span className="dot" style={{ background: COLOR.sig }} /> chart signal</li>
        <li><span className="dot" style={{ background: COLOR.oos }} /> out of spec</li>
        <li><span className="dot" style={{ background: COLOR.fix }} /> van just fixed it</li>
        <li>each station: one bike per docked bike; kiosk light = status · cyclists = the rider trips of the next 15 min (models 14× life size)</li>
        <li>map colours follow the time of day (night, dawn, day, sunset, dusk)</li>
        <li>drag to pan · right-drag or ctrl-drag to tilt and rotate</li>
      </ul>
    </div>
  )
}
