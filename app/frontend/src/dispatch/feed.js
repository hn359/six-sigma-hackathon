// Pure helpers for the dispatch console. No statistics: triggers, moves and chart values all
// arrive in the frames from the API (app/qc.py). This file only turns frames into words,
// colours and a van route.

export const DEPOT = { id: 'depot', name: 'Reserve depot (Collegetown)', lat: 42.4422, lon: -76.4856 }

export const clock = (asOf) => (asOf ? asOf.slice(11, 16) : '')
export const slotClock = (k) => {
  const m = 360 + 15 * k
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

const DRIFT = { empty: 'draining faster than usual', full: 'filling faster than usual' }

// Status of one station at frame i, for the label and the feed.
// 'sig' a run rule fired, 'oos' out of spec only, 'fix' the van stopped here at this reading,
// 'back' back in control within two readings of a van stop, 'ok' in control.
export function stationStatus(frames, i, id) {
  const f = frames[i]
  const s = f?.stations.find((x) => x.station_id === id)
  if (!s) return { cls: 'ok', text: '' }
  if (s.van_moved) return { cls: 'fix', text: `van ${s.van_moved > 0 ? '+' : ''}${s.van_moved}` }
  if (s.trigger?.startsWith('rule')) return { cls: 'sig', text: `${s.trigger}, ${s.direction === 'empty' ? 'draining' : 'filling'}` }
  if (s.trigger) return { cls: 'oos', text: s.bikes < 4 ? 'below 4 bikes' : 'above 16 bikes' }
  for (let j = i - 1; j >= Math.max(0, i - 2); j--) {
    const p = frames[j].stations.find((x) => x.station_id === id)
    if (p?.van_moved) return { cls: 'back', text: 'back in control' }
  }
  return { cls: 'ok', text: i === 0 ? 'day start' : 'in control' }
}

// Feed entries for frames 0..i, newest first.
export function feedEntries(frames, i, names = {}) {
  const out = []
  for (let k = Math.min(i, frames.length - 1); k >= 0; k--) {
    const f = frames[k]
    const chips = f.stations.map((s) => ({
      id: s.station_id, bikes: s.bikes,
      cls: s.trigger?.startsWith('rule') ? 'sig' : s.trigger ? 'oos' : '',
    }))
    const events = []
    for (const s of f.stations) {
      if (s.trigger?.startsWith('rule')) events.push({ cls: 'sig', text: `${s.station_id}: ${s.trigger} (${s.rule}), ${DRIFT[s.direction]}` })
      else if (s.trigger) events.push({ cls: 'oos', text: `${s.station_id}: ${s.bikes} bikes, out of spec` })
      if (s.trigger && s.bikes_to_move === 0) events.push({ cls: 'muted', text: `${s.station_id}: already past its expected path, nothing to move` })
    }
    if (f.van) events.push({ cls: 'van', text: vanSentence(f, names) })
    else if (f.stations.some((s) => s.trigger && s.bikes_to_move)) events.push({ cls: 'muted', text: 'No van sent at this reading' })
    for (const s of f.stations) {
      if (stationStatus(frames, k, s.station_id).cls === 'back' &&
          !(k > 0 && stationStatus(frames, k - 1, s.station_id).cls === 'back'))
        events.push({ cls: 'ok', text: `${s.station_id} back in control: ${s.bikes} bikes, no signal` })
    }
    out.push({ asOf: f.as_of, chips, events })
  }
  return out
}

export function vanSentence(f, names = {}) {
  const v = f.van
  const t = f.stations.find((s) => s.station_id === v.station_id)
  const n = Math.abs(v.bikes_moved)
  const parts = []
  if (v.partner_bikes) parts.push(`${v.partner_bikes} ${v.bikes_moved > 0 ? 'from' : 'to'} ${v.partner}`)
  if (v.reserve_bikes) parts.push(`${v.reserve_bikes} ${v.bikes_moved > 0 ? 'from' : 'to'} the reserve`)
  const name = names[v.station_id] ? ` ${names[v.station_id]}` : ''
  return `Van → ${v.station_id}${name}: ${v.bikes_moved > 0 ? 'brought' : 'took'} ${n} (${parts.join(', ')}), ` +
    `${t.bikes} → ${t.bikes_after_van} bikes`
}

// The van's stops for a frame: bringing bikes = collect (other station, depot) then drop;
// taking bikes = collect at the station, then drop (other station, depot).
export function vanStops(van) {
  if (!van) return []
  const collect = []
  if (van.partner_bikes) collect.push(van.partner)
  if (van.reserve_bikes) collect.push('depot')
  return van.bikes_moved > 0 ? [...collect, van.station_id] : [van.station_id, ...collect]
}

// Where the van is parked after frame i: the last stop of the last trip, else the depot.
export function vanHome(frames, i) {
  for (let k = Math.min(i, frames.length - 1); k >= 0; k--) {
    const stops = vanStops(frames[k].van)
    if (stops.length) return stops[stops.length - 1]
  }
  return 'depot'
}
