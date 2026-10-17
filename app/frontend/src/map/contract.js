// Checks that a frame from the back end has the shape the map needs.
// The rules are written out in docs/map-contract.md; keep the two in step.
// No statistics here: the map never recomputes a limit or a move, it only
// refuses to show numbers that cannot be right together.

const DIRECTIONS = new Set(['empty', 'full', 'ok'])
// v2: why the van is sent. A frame with a `trigger` field is checked by the v2 rules.
const TRIGGERS = new Set(['rule 1', 'rule 2', 'rule 3', 'rule 4', 'out of spec'])

const isNum = (x) => typeof x === 'number' && Number.isFinite(x)
const isInt = (x) => Number.isInteger(x)

export function validateStation(s) {
  const e = []
  if (!s || typeof s !== 'object') return ['not an object']
  if (typeof s.station_id !== 'string' || s.station_id === '') e.push('station_id missing')
  if (typeof s.name !== 'string') e.push('name missing')

  const capOk = isInt(s.capacity) && s.capacity > 0
  const bikesOk = isInt(s.bikes) && s.bikes >= 0 && capOk && s.bikes <= s.capacity
  if (!capOk) e.push(`capacity must be a positive whole number (got ${s.capacity})`)
  if (!bikesOk) e.push(`bikes must be a whole number from 0 to capacity (got ${s.bikes})`)

  // rule 1: occupancy = bikes / capacity
  if (!isNum(s.occupancy)) e.push('occupancy missing')
  else if (bikesOk && Math.abs(s.occupancy - s.bikes / s.capacity) > 0.01)
    e.push(`rule 1: occupancy ${s.occupancy} is not bikes/capacity = ${(s.bikes / s.capacity).toFixed(3)}`)

  // rule 2: severity 0-3, direction "ok" exactly when severity is 0
  const sevOk = isInt(s.severity) && s.severity >= 0 && s.severity <= 3
  if (!sevOk) e.push(`rule 2: severity must be 0, 1, 2 or 3 (got ${s.severity})`)
  if (!DIRECTIONS.has(s.direction)) e.push(`rule 2: direction must be empty, full or ok (got ${s.direction})`)
  else if (sevOk && (s.severity === 0) !== (s.direction === 'ok'))
    e.push(`rule 2: direction "${s.direction}" does not fit severity ${s.severity}`)

  if (s.target_occupancy !== null && s.target_occupancy !== undefined &&
      !(isNum(s.target_occupancy) && s.target_occupancy >= 0 && s.target_occupancy <= 1))
    e.push(`target_occupancy must be a share from 0 to 1 (got ${s.target_occupancy})`)

  // v2: trigger names why the van is sent; severity is 0 exactly when there is no trigger
  const v2 = 'trigger' in s
  if (v2) {
    if (s.trigger !== null && !TRIGGERS.has(s.trigger))
      e.push(`rule 2: trigger must be rule 1-4, "out of spec" or null (got ${s.trigger})`)
    else if (sevOk && (s.severity === 0) !== (s.trigger === null))
      e.push(`rule 2: trigger ${s.trigger} does not fit severity ${s.severity}`)
    if (s.expected_bikes !== undefined && s.expected_bikes !== null &&
        !(isNum(s.expected_bikes) && s.expected_bikes >= 0 && capOk && s.expected_bikes <= s.capacity))
      e.push(`expected_bikes must be from 0 to capacity (got ${s.expected_bikes})`)
  }

  // rules 3-5: bikes_to_move (v2 allows 0: the station is already past its path, nothing to move)
  const m = s.bikes_to_move
  if (sevOk && s.severity === 0) {
    if (m !== null) e.push(`rule 3: in control, so bikes_to_move must be null (got ${m})`)
  } else if (sevOk) {
    if (!isInt(m) || (m === 0 && !v2)) e.push(`rule 3: out of control, so bikes_to_move must be a non-zero whole number (got ${m})`)
    else {
      if (s.direction === 'empty' && m < 0) e.push(`rule 4: too empty but bikes_to_move ${m} removes bikes`)
      if (s.direction === 'full' && m > 0) e.push(`rule 4: too full but bikes_to_move +${m} adds bikes`)
      if (bikesOk && (m < -s.bikes || m > s.capacity - s.bikes))
        e.push(`rule 5: cannot move ${m} with ${s.bikes} bikes in ${s.capacity} docks`)
    }
  }

  // rule 6: coordinates
  if (!isNum(s.lat) || !isNum(s.lon) || Math.abs(s.lat) > 90 || Math.abs(s.lon) > 180)
    e.push('rule 6: lat/lon missing or out of range')

  return e
}

export function validateFrame(frame) {
  if (!frame || typeof frame !== 'object') return { ok: false, errors: ['frame is not an object'] }
  const errors = []
  if (typeof frame.as_of !== 'string' || Number.isNaN(Date.parse(frame.as_of)))
    errors.push(`as_of is not a date-time (got ${frame.as_of})`)
  if (!Array.isArray(frame.stations)) {
    errors.push('stations is not a list')
    return { ok: false, errors }
  }
  const seen = new Set()
  for (const s of frame.stations) {
    const id = s?.station_id ?? '?'
    if (seen.has(id)) errors.push(`${id}: appears twice`)
    seen.add(id)
    for (const msg of validateStation(s)) errors.push(`${id}: ${msg}`)
  }
  // v2 frame fields: the van's stop after this reading and the reserve depot
  if (frame.van !== undefined && frame.van !== null) {
    const v = frame.van
    if (!isInt(v.bikes_moved) || v.bikes_moved === 0) errors.push(`van: bikes_moved must be a non-zero whole number (got ${v.bikes_moved})`)
    if (!seen.has(v.station_id)) errors.push(`van: station ${v.station_id} is not in this frame`)
  }
  if (frame.reserve !== undefined && !(isInt(frame.reserve) && frame.reserve >= 0))
    errors.push(`reserve must be a whole number of bikes (got ${frame.reserve})`)
  return { ok: errors.length === 0, errors }
}
