import { Fragment, useEffect } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import {
  bikesToMoveLabel, COLORS, directionLabel, ITHACA_CENTER, ITHACA_ZOOM,
  markerStyle, pct, rankStations, SEVERITY_LABELS, splitPlaceable,
} from './stationMap.js'
import './map.css'

// Pans to the selected station without resetting the zoom the dispatcher chose.
function FollowSelected({ station }) {
  const map = useMap()
  useEffect(() => {
    if (station) map.panTo([station.lat, station.lon], { animate: true })
  }, [map, station])
  return null
}

// stations: one replay frame (see sampleFrames.js for the shape).
// Dark mode: the same OpenStreetMap tiles (no API key), darkened by a CSS filter on the
// 'dark-tiles' class (see src/dispatch/dispatch.css), plus brighter colours and bigger dots.
const DARK = {
  url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  colors: { empty: '#e5484d', full: '#6f88fc', ok: '#12b8da' },
  // The console draws each station's gauge and halo itself (src/dispatch/VanLayer.jsx), centred
  // on the point; the dot stays as an invisible click target so selecting still works.
  clickRadius: 30,
  selected: '#ffffff',
}

// children: extra layers drawn inside the map (the console adds the van, the depot and counts).
// dark: optional dark mode; without it the map looks exactly as before.
export function StationMap({ stations, selectedId, onSelect, children, className = 'map', dark = false }) {
  const { placed, missing } = splitPlaceable(stations)
  const selected = placed.find((s) => s.station_id === selectedId)

  return (
    <div className="map-wrap">
      <MapContainer center={ITHACA_CENTER} zoom={ITHACA_ZOOM} className={className} scrollWheelZoom>
        {dark
          ? <TileLayer attribution={DARK.attribution} url={DARK.url} maxZoom={19} className="dark-tiles" />
          : <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />}
        {placed.map((s) => {
          const base = markerStyle(s)
          const style = dark
            ? { ...base, radius: DARK.clickRadius, color: DARK.colors[colorKey(base)], fillColor: DARK.colors[colorKey(base)],
                fillOpacity: 0, opacity: 0 }
            : base
          const isSel = s.station_id === selectedId
          return (
            <Fragment key={s.station_id}>
              <CircleMarker
                center={[s.lat, s.lon]}
                radius={style.radius}
                pathOptions={{ ...style, weight: isSel ? 3 : style.weight, color: isSel ? (dark ? DARK.selected : '#111') : style.color,
                  opacity: isSel ? 1 : style.opacity }}
                eventHandlers={{ click: () => onSelect?.(s.station_id) }}
              >
                <Tooltip direction="top" offset={[0, -style.radius]}>
                  <strong>{s.name}</strong><br />
                  {s.bikes} of {s.capacity} docks filled ({pct(s.occupancy)}), {directionLabel(s)}
                  {s.rule && <><br />{s.rule}</>}
                  {s.bikes_to_move !== null && s.bikes_to_move !== undefined && (
                    <><br /><strong>{bikesToMoveLabel(s.bikes_to_move)} bikes</strong> (target {pct(s.target_occupancy)})</>
                  )}
                </Tooltip>
              </CircleMarker>
            </Fragment>
          )
        })}
        {children}
        <FollowSelected station={selected} />
      </MapContainer>
      <Legend colors={dark ? DARK.colors : COLORS} sizeNote={dark ? 'bigger halo = more severe; ring = share of docks filled' : undefined} />
      {missing.length > 0 && (
        <p className="map-missing">
          Not on the map (no coordinates): {missing.map((s) => s.station_id).join(', ')}
        </p>
      )}
    </div>
  )
}

// which palette entry a base marker colour is
function colorKey(style) {
  return Object.keys(COLORS).find((k) => COLORS[k] === style.color) ?? 'ok'
}

function Legend({ colors = COLORS, sizeNote = 'bigger dot = more severe' }) {
  return (
    <ul className="map-legend" aria-label="Map legend">
      <li><span className="dot" style={{ background: colors.empty }} /> too empty</li>
      <li><span className="dot" style={{ background: colors.full }} /> too full</li>
      <li><span className="dot" style={{ background: colors.ok }} /> in control</li>
      <li>{sizeNote}</li>
    </ul>
  )
}

// Ranked "act now" list. Clicking a row selects the station on the map.
export function ActionList({ stations, selectedId, onSelect }) {
  const ranked = rankStations(stations)
  if (ranked.length === 0) return <p className="act-empty">No stations in this frame.</p>
  return (
    <ol className="act-list">
      {ranked.map((s) => (
        <li key={s.station_id}>
          <button
            type="button"
            className={s.station_id === selectedId ? 'act-row sel' : 'act-row'}
            onClick={() => onSelect?.(s.station_id)}
          >
            <span className="act-name">
              <span className="dot" style={{ background: markerStyle(s).color }} />
              {s.name}
            </span>
            <span className="act-move" title={`bikes to move to reach the target, ${pct(s.target_occupancy)} full`}>
              {bikesToMoveLabel(s.bikes_to_move)}
            </span>
            <span className="act-why">
              {s.severity > 0 ? `${directionLabel(s)}, ${SEVERITY_LABELS[s.severity]}: ${s.rule}` : 'in control'}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
