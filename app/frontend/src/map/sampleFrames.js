// INVENTED SAMPLE DATA - not real Ithaca bikeshare readings.
// Five made-up stations placed at real Ithaca places (coordinates approximate),
// with a made-up weekday: Main Campus fills up in the morning while North Campus
// and Fall Creek empty, then the reverse in the evening; Wegmans fills after work.
// Severity, direction and bikes_to_move here are hand-picked or stand-in values
// for what the back end (app/qc.py) will compute; the map only needs the shape
// in docs/map-contract.md. Replace with POST /replay output once it exists.

import { READING_EVERY_MIN } from './stationMap.js'

// Hand-written key times; the readings in between are filled in below so the
// sample has one frame every 15 minutes, like the real feed (06:00-22:00).
const KEY_TIMES = [
  '06:00', '07:00', '07:30', '08:00', '08:30', '09:00',
  '12:00', '16:30', '17:00', '17:30', '18:00', '22:00',
]
const DAY = '2026-10-12'

// usual = the station's normal occupancy (one number per station, a fixture
// simplification; the real tool learns one per time of day).
const STATIONS = [
  { id: 'S01', name: 'North Campus (RPCC)', lat: 42.4556, lon: -76.4778, cap: 15, usual: 0.55,
    bikes: [9, 6, 4, 2, 1, 1, 2, 6, 8, 10, 12, 10], sev: [0, 0, 1, 2, 3, 3, 2, 0, 0, 0, 1, 0] },
  { id: 'S02', name: 'Main Campus (Ho Plaza)', lat: 42.4470, lon: -76.4833, cap: 23, usual: 0.45,
    bikes: [9, 12, 16, 20, 22, 23, 21, 15, 10, 6, 4, 8], sev: [0, 0, 1, 2, 3, 3, 2, 0, 0, 1, 2, 0] },
  { id: 'S03', name: 'Fall Creek', lat: 42.4495, lon: -76.4953, cap: 11, usual: 0.55,
    bikes: [7, 4, 2, 1, 0, 0, 1, 4, 5, 7, 9, 7], sev: [0, 1, 2, 3, 3, 3, 2, 0, 0, 0, 1, 0],
    availability: 0.71 },
  { id: 'S04', name: 'Downtown (Ithaca Commons)', lat: 42.4392, lon: -76.4964, cap: 19, usual: 0.50,
    bikes: [10, 9, 9, 8, 9, 10, 13, 10, 9, 8, 9, 10], sev: [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0] },
  { id: 'S05', name: 'Wegmans (Meadow St)', lat: 42.4334, lon: -76.5108, cap: 15, usual: 0.50,
    bikes: [8, 8, 7, 7, 8, 8, 9, 10, 12, 14, 13, 8], sev: [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 0] },
]

const RULES = [null, '8 in a row on one side', '2 of 3 beyond 2 sigma', '1 point beyond 3 sigma']

// STAND-IN for the back end's rule, only so the sample shows numbers: move the
// station back to `usual`, whole bikes, never more than the bikes or free docks
// it has. The real rule (which centre line, how to round) is the back end's.
function standInMove(bikes, cap, target) {
  let m = Math.round((target - bikes / cap) * cap)
  if (m === 0) m = target > bikes / cap ? 1 : -1
  return Math.max(-bikes, Math.min(cap - bikes, m))
}

const toMin = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3))
const toHHMM = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
const KEY_MIN = KEY_TIMES.map(toMin)

// Between two key times: bikes move in a straight line (whole bikes), and the
// severity of the earlier key time holds, dropped to 0 once the station is
// back within 10 points of usual. Invented, only to fill the 15-min grid.
function stationAt(s, minute) {
  let k = KEY_MIN.length - 1
  while (KEY_MIN[k] > minute) k -= 1
  const next = Math.min(k + 1, KEY_MIN.length - 1)
  const f = next === k ? 0 : (minute - KEY_MIN[k]) / (KEY_MIN[next] - KEY_MIN[k])
  const bikes = Math.round(s.bikes[k] + f * (s.bikes[next] - s.bikes[k]))
  const occupancy = bikes / s.cap
  const gap = occupancy - s.usual
  const severity = Math.abs(gap) < 0.1 ? 0 : s.sev[k]
  return {
    station_id: s.id,
    name: s.name,
    lat: s.lat,
    lon: s.lon,
    capacity: s.cap,
    bikes,
    occupancy,
    gap,
    direction: severity === 0 ? 'ok' : gap < 0 ? 'empty' : 'full',
    severity,
    rule: RULES[severity],
    target_occupancy: s.usual,
    bikes_to_move: severity === 0 ? null : standInMove(bikes, s.cap, s.usual),
    availability: s.availability ?? null,
  }
}

const MINUTES = []
for (let m = KEY_MIN[0]; m <= KEY_MIN[KEY_MIN.length - 1]; m += READING_EVERY_MIN) MINUTES.push(m)

export const FRAMES = MINUTES.map((m) => ({
  as_of: `${DAY}T${toHHMM(m)}`,
  stations: STATIONS.map((s) => stationAt(s, m)),
}))
