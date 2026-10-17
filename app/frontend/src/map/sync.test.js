import { describe, expect, it, vi } from 'vitest'
import { createSimulationState, isSimulationState, publishSimulationState } from './sync.js'

const ready = () => createSimulationState({
  city: 'collegetown', scenario: 'event', asOf: '2026-10-19T08:30', intervalMinutes: 15,
  stations: [{ station_id: 'S01', bikes: 12, capacity: 20 }], reserve: 8, playing: true,
})

describe('simulation state bridge', () => {
  it('publishes a versioned, exact reading snapshot', () => {
    const state = ready()
    expect(isSimulationState(state)).toBe(true)
    expect(state).toMatchObject({ type: 'sixsigma.simulation-state', version: 1,
      status: 'ready', city: 'collegetown', scenario: 'event', as_of: '2026-10-19T08:30',
      source: 'replay', interval_minutes: 15, playing: true })
    expect(state.stations).toEqual([{ station_id: 'S01', bikes: 12, capacity: 20 }])
  })

  it('does not publish an old frame while the selected scenario is loading', () => {
    const state = createSimulationState({ city: 'downtown', scenario: 'week11', status: 'loading' })
    expect(isSimulationState(state)).toBe(true)
    expect(state.as_of).toBeNull()
    expect(state.stations).toEqual([])
  })

  it('accepts numbered policy weeks while rejecting invalid week names', () => {
    const state = createSimulationState({ city: 'collegetown', scenario: 'week11', status: 'loading' })
    expect(isSimulationState(state)).toBe(true)
    expect(() => createSimulationState({ city: 'collegetown', scenario: 'week0', status: 'loading' }))
      .toThrow('invalid simulation scenario')
    expect(isSimulationState({ ...state, scenario: 'week0' })).toBe(false)
  })

  it('rejects malformed ready frames and unsupported versions', () => {
    expect(() => createSimulationState({ city: 'x', scenario: 'event', stations: [] }))
      .toThrow('a ready state needs an exact reading time, station inventory, and reserve count')
    expect(isSimulationState({ ...ready(), version: 99 })).toBe(false)
    expect(isSimulationState({ ...ready(), as_of: 'yesterday' })).toBe(false)
  })

  it('uses the same origin for the parent message', () => {
    const target = { postMessage: vi.fn() }
    const state = ready()
    expect(publishSimulationState(state, target, 'http://127.0.0.1:8000')).toBe(true)
    expect(target.postMessage).toHaveBeenCalledWith(state, 'http://127.0.0.1:8000')
  })

  it('rejects duplicate or invalid station inventory rows', () => {
    expect(isSimulationState({ ...ready(), stations:[{ station_id:'S01', bikes:12, capacity:20 }, { station_id:'S01', bikes:8, capacity:20 }] })).toBe(false)
    expect(isSimulationState({ ...ready(), stations:[{ station_id:'S01', bikes:-1, capacity:20 }] })).toBe(false)
    expect(isSimulationState({ ...ready(), stations:[{ station_id:'S01', bikes:21, capacity:20 }] })).toBe(false)
  })
})
