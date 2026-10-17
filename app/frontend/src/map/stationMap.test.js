import { describe, expect, it } from 'vitest'
import {
  bikesToMoveLabel, clampSeverity, COLORS, directionLabel, markerStyle,
  rankStations, splitPlaceable,
} from './stationMap.js'
import { FRAMES } from './sampleFrames.js'

const st = (id, severity, direction, gap, extra = {}) =>
  ({ station_id: id, severity, direction, gap, lat: 42.44, lon: -76.49, ...extra })

describe('markerStyle', () => {
  it('in control is small and grey, whatever the direction says', () => {
    const m = markerStyle(st('A', 0, 'empty', -0.3))
    expect(m.radius).toBe(7)
    expect(m.color).toBe(COLORS.ok)
  })
  it('severity grows the dot and direction sets the colour', () => {
    expect(markerStyle(st('A', 3, 'empty', -0.4))).toMatchObject({ radius: 19, color: COLORS.empty })
    expect(markerStyle(st('B', 1, 'full', 0.2))).toMatchObject({ radius: 11, color: COLORS.full })
  })
  it('bad severity falls back to in control, never NaN', () => {
    expect(clampSeverity(undefined)).toBe(0)
    expect(clampSeverity(9)).toBe(3)
    expect(markerStyle(st('A', NaN, 'full', 0)).radius).toBe(7)
  })
})

describe('rankStations', () => {
  it('keeps every station; orders by severity, then |gap|, then id', () => {
    const ranked = rankStations([
      st('S1', 0, 'ok', 0.0),
      st('S2', 2, 'full', 0.30),
      st('S3', 3, 'empty', -0.20),
      st('S4', 2, 'empty', -0.45),
      st('S5', 2, 'full', 0.45),
    ])
    expect(ranked.map((s) => s.station_id)).toEqual(['S3', 'S4', 'S5', 'S2', 'S1'])
  })
  it('an all-calm network still lists every station', () => {
    expect(rankStations([st('S2', 0, 'ok', 0), st('S1', 0, 'ok', 0)]).map((s) => s.station_id))
      .toEqual(['S1', 'S2'])
  })
})

describe('labels', () => {
  it('bikes to move', () => {
    expect(bikesToMoveLabel(null)).toBe('—')
    expect(bikesToMoveLabel(6)).toBe('add 6')
    expect(bikesToMoveLabel(-4)).toBe('remove 4')
    expect(bikesToMoveLabel(0)).toBe('—')
  })
  it('direction', () => {
    expect(directionLabel(st('A', 2, 'empty', -0.3))).toBe('too empty')
    expect(directionLabel(st('A', 1, 'full', 0.3))).toBe('too full')
    expect(directionLabel(st('A', 0, 'full', 0.3))).toBe('in control')
  })
})

describe('splitPlaceable', () => {
  it('keeps stations with no coordinates in a missing list', () => {
    const { placed, missing } = splitPlaceable([
      st('A', 3, 'empty', -0.4), st('B', 0, 'ok', 0, { lat: null }), st('C', 1, 'full', 0.2),
    ])
    expect(placed.map((s) => s.station_id)).toEqual(['C', 'A'])
    expect(missing.map((s) => s.station_id)).toEqual(['B'])
  })
})

describe('sample frames (invented)', () => {
  it('one frame every 15 minutes from 06:00 to 22:00', () => {
    expect(FRAMES).toHaveLength(65)
    expect(FRAMES[0].as_of).toBe('2026-10-12T06:00')
    expect(FRAMES[10].as_of).toBe('2026-10-12T08:30')
    expect(FRAMES[64].as_of).toBe('2026-10-12T22:00')
    for (let k = 1; k < FRAMES.length; k += 1)
      expect(Date.parse(FRAMES[k].as_of) - Date.parse(FRAMES[k - 1].as_of)).toBe(15 * 60_000)
  })

  it('every station sits inside the Ithaca area and has occupancy = bikes / capacity', () => {
    for (const f of FRAMES) {
      for (const s of f.stations) {
        expect(s.lat).toBeGreaterThan(42.40)
        expect(s.lat).toBeLessThan(42.48)
        expect(s.lon).toBeGreaterThan(-76.53)
        expect(s.lon).toBeLessThan(-76.46)
        expect(s.occupancy).toBeCloseTo(s.bikes / s.capacity, 10)
        expect(s.bikes).toBeLessThanOrEqual(s.capacity)
      }
    }
  })
})
