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
export function StationMap({ stations, selectedId, onSelect }) {
  const { placed, missing } = splitPlaceable(stations)
  const selected = placed.find((s) => s.station_id === selectedId)

  return (
    <div className="map-wrap">
      <MapContainer center={ITHACA_CENTER} zoom={ITHACA_ZOOM} className="map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {placed.map((s) => {
          const style = markerStyle(s)
          const isSel = s.station_id === selectedId
          return (
            <Fragment key={s.station_id}>
              {s.chronic_flag && (
                <CircleMarker
                  center={[s.lat, s.lon]}
                  radius={style.radius + 5}
                  pathOptions={{ color: '#7a1f1f', weight: 2, dashArray: '4 3', fill: false }}
                  interactive={false}
                />
              )}
              <CircleMarker
                center={[s.lat, s.lon]}
                radius={style.radius}
                pathOptions={{ ...style, weight: isSel ? 3 : style.weight, color: isSel ? '#111' : style.color }}
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
        <FollowSelected station={selected} />
      </MapContainer>
      <Legend />
      {missing.length > 0 && (
        <p className="map-missing">
          Not on the map (no coordinates): {missing.map((s) => s.station_id).join(', ')}
        </p>
      )}
    </div>
  )
}

function Legend() {
  return (
    <ul className="map-legend" aria-label="Map legend">
      <li><span className="dot" style={{ background: COLORS.empty }} /> too empty</li>
      <li><span className="dot" style={{ background: COLORS.full }} /> too full</li>
      <li><span className="dot" style={{ background: COLORS.ok }} /> in control</li>
      <li>bigger dot = more severe</li>
      <li><span className="ring" /> chronic: send a repair crew</li>
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
              {s.chronic_flag && ' · chronic'}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}
