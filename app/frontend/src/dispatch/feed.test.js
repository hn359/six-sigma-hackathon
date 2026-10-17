import { describe, expect, it } from 'vitest'
import { feedEntries, slotClock, stationStatus, vanHome, vanSentence, vanStops } from './feed.js'
import example from '../../../../docs/map-frame.example.json'

const st = (id, patch = {}) => ({
  station_id: id, bikes: 10, trigger: null, rule: null, direction: 'ok', bikes_to_move: null,
  van_moved: 0, bikes_after_van: 10, ...patch,
})
const frame = (k, stations, van = null) => ({ as_of: `2026-10-19T${slotClock(k)}`, slot: k, stations, van })

describe('van route', () => {
  it('bringing bikes: collect from the other station and the depot, then drop', () => {
    expect(vanStops({ station_id: 'S03', bikes_moved: 4, partner: 'S05', partner_bikes: 3, reserve_bikes: 1 }))
      .toEqual(['S05', 'depot', 'S03'])
  })
  it('taking bikes: collect at the station, then drop', () => {
    expect(vanStops(example.van)).toEqual(['S02', 'S04', 'depot'])
  })
  it('the van parks at its last stop, or the depot before any trip', () => {
    const frames = [frame(0, [st('S01')]), frame(1, [st('S01')], { station_id: 'S01', bikes_moved: 2, partner: null, partner_bikes: 0, reserve_bikes: 2 })]
    expect(vanHome(frames, 0)).toBe('depot')
    expect(vanHome(frames, 1)).toBe('S01')
  })
})

describe('status and feed', () => {
  const frames = [
    frame(0, [st('S02')]),
    frame(1, [st('S02', { bikes: 15, trigger: 'rule 1', rule: '1 point beyond 3 sigma', direction: 'full', bikes_to_move: -3, van_moved: -3, bikes_after_van: 12 })],
      { station_id: 'S02', bikes_moved: -3, partner: null, partner_bikes: 0, reserve_bikes: 3 }),
    frame(2, [st('S02', { bikes: 12 })]),
    frame(3, [st('S02', { bikes: 12 })]),
    frame(4, [st('S02', { bikes: 12 })]),
  ]
  it('names the van stop, then back in control once, then in control', () => {
    expect(stationStatus(frames, 1, 'S02').cls).toBe('fix')
    expect(stationStatus(frames, 2, 'S02').cls).toBe('back')
    expect(stationStatus(frames, 4, 'S02').cls).toBe('ok')
    const texts = feedEntries(frames, 4).flatMap((e) => e.events.map((x) => x.text))
    expect(texts.filter((t) => t.includes('back in control'))).toHaveLength(1)
  })
  it('the feed is newest first with a chip per station', () => {
    const feed = feedEntries(frames, 2)
    expect(feed.map((e) => e.asOf.slice(11))).toEqual(['06:30', '06:15', '06:00'])
    expect(feed[1].chips[0]).toEqual({ id: 'S02', bikes: 15, cls: 'sig' })
  })
  it('the van sentence says where bikes came from and the before/after count', () => {
    expect(vanSentence(example)).toBe('Van → S02: took 3 (2 to S04, 1 to the reserve), 10 → 7 bikes')
  })
})
