import { describe, expect, it } from 'vitest'
import { validateFrame } from './contract.js'
import { FRAMES } from './sampleFrames.js'
import example from '../../../../docs/map-frame.example.json'

// A good out-of-control station: 2 of 11 docks filled, too empty, add 4.
const good = () => ({
  station_id: 'S03', name: 'Fall Creek', lat: 42.4495, lon: -76.4953, capacity: 11,
  bikes: 2, occupancy: 2 / 11, gap: -0.37, direction: 'empty', severity: 3,
  rule: '1 point beyond 3 sigma', target_occupancy: 0.55, bikes_to_move: 4,
  chronic_flag: true, availability: 0.71,
})
const frameOf = (...stations) => ({ as_of: '2026-10-12T08:30', stations })
const errorsFor = (patch) => validateFrame(frameOf({ ...good(), ...patch })).errors

describe('validateFrame accepts', () => {
  it('a good station', () => {
    expect(validateFrame(frameOf(good()))).toEqual({ ok: true, errors: [] })
  })
  it('every invented sample frame', () => {
    for (const f of FRAMES) expect(validateFrame(f).errors).toEqual([])
  })
  it('the example frame in docs/map-frame.example.json', () => {
    expect(validateFrame(example).errors).toEqual([])
  })
  it('an in-control station with a null move', () => {
    expect(errorsFor({ severity: 0, direction: 'ok', bikes_to_move: null, rule: null })).toEqual([])
  })
})

describe('validateFrame rejects, naming station and rule', () => {
  it('rule 1: occupancy that is not bikes / capacity', () => {
    expect(errorsFor({ occupancy: 0.5 })[0]).toMatch(/^S03: rule 1/)
  })
  it('rule 2: direction "ok" on an out-of-control station', () => {
    expect(errorsFor({ direction: 'ok' }).join()).toMatch(/rule 2/)
  })
  it('rule 2: severity outside 0-3', () => {
    expect(errorsFor({ severity: 5 }).join()).toMatch(/rule 2/)
  })
  it('rule 3: a move on an in-control station', () => {
    expect(errorsFor({ severity: 0, direction: 'ok', bikes_to_move: 3 }).join()).toMatch(/rule 3/)
  })
  it('rule 3: no move on an out-of-control station', () => {
    expect(errorsFor({ bikes_to_move: null }).join()).toMatch(/rule 3/)
    expect(errorsFor({ bikes_to_move: 2.5 }).join()).toMatch(/rule 3/)
  })
  it('rule 4: adding bikes to a full station', () => {
    expect(errorsFor({ bikes: 10, occupancy: 10 / 11, direction: 'full', bikes_to_move: 1 }).join())
      .toMatch(/rule 4/)
  })
  it('rule 5: a move larger than the free docks', () => {
    expect(errorsFor({ bikes_to_move: 10 }).join()).toMatch(/rule 5/)
  })
  it('rule 5: removing more bikes than the station has', () => {
    expect(errorsFor({ bikes: 10, occupancy: 10 / 11, direction: 'full', bikes_to_move: -11 }).join())
      .toMatch(/rule 5/)
  })
  it('rule 6: a missing lat', () => {
    expect(errorsFor({ lat: null }).join()).toMatch(/rule 6/)
  })
  it('a frame that is not a frame', () => {
    expect(validateFrame(null).ok).toBe(false)
    expect(validateFrame({ as_of: 'yesterday', stations: 'S01' }).errors).toHaveLength(2)
  })
  it('the same station twice', () => {
    expect(validateFrame(frameOf(good(), good())).errors).toContain('S03: appears twice')
  })
})
