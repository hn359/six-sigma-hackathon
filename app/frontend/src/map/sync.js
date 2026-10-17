export const SIMULATION_STATE_TYPE = 'sixsigma.simulation-state'
export const SIMULATION_STATE_VERSION = 1
const isSimulationScenario = (scenario) => typeof scenario === 'string' &&
  (scenario === 'event' || /^week[1-9]\d*$/.test(scenario))

export function createSimulationState({
  status = 'ready', city, scenario, dayIndex = 0, source = 'replay', intervalMinutes = 15,
  asOf = null, playing = false, stations = [], reserve = 0, reason = '',
}) {
  if (!['ready', 'loading', 'error'].includes(status)) throw new Error('invalid simulation state status')
  if (typeof city !== 'string' || !city) throw new Error('simulation state needs a city')
  if (!isSimulationScenario(scenario)) throw new Error('invalid simulation scenario')
  if (!Number.isInteger(dayIndex) || dayIndex < 0) throw new Error('day index must be a non-negative integer')
  if (!['replay', 'live'].includes(source)) throw new Error('invalid simulation source')
  if (!Number.isInteger(intervalMinutes) || intervalMinutes < 1) throw new Error('invalid reading interval')
  if (status === 'ready' && (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(asOf || '') || !Array.isArray(stations) ||
      !stations.length || !Number.isInteger(reserve) || reserve < 0 ||
      !stations.every(x => typeof x.station_id === 'string' && x.station_id && Number.isInteger(x.bikes) &&
        Number.isInteger(x.capacity) && x.capacity > 0 && x.bikes >= 0 && x.bikes <= x.capacity) ||
      new Set(stations.map(x => x.station_id)).size !== stations.length)) {
    throw new Error('a ready state needs an exact reading time, station inventory, and reserve count')
  }
  return {
    type: SIMULATION_STATE_TYPE,
    version: SIMULATION_STATE_VERSION,
    status,
    city,
    scenario,
    day_index: dayIndex,
    source,
    interval_minutes: intervalMinutes,
    as_of: status === 'ready' ? asOf : null,
    playing: Boolean(playing),
    stations: status === 'ready' ? stations.map(({ station_id, bikes, capacity }) => ({ station_id, bikes, capacity })) : [],
    reserve: status === 'ready' ? reserve : null,
    reason: status === 'error' ? String(reason || 'The simulation frame could not load.') : '',
  }
}

export function publishSimulationState(state, target = globalThis.window?.parent,
  targetOrigin = globalThis.window?.location?.origin) {
  if (!target || target === globalThis.window || !targetOrigin) return false
  target.postMessage(state, targetOrigin)
  return true
}

export function isSimulationState(value) {
  return Boolean(value && typeof value === 'object' &&
    value.type === SIMULATION_STATE_TYPE && value.version === SIMULATION_STATE_VERSION &&
    ['ready', 'loading', 'error'].includes(value.status) &&
    typeof value.city === 'string' && isSimulationScenario(value.scenario) &&
    Number.isInteger(value.day_index) && value.day_index >= 0 &&
    ['replay', 'live'].includes(value.source) && Number.isInteger(value.interval_minutes) &&
    value.interval_minutes > 0 && typeof value.playing === 'boolean' && typeof value.reason === 'string' &&
    Array.isArray(value.stations) && (value.status === 'ready'
      ? (/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(value.as_of || '') && value.stations.length > 0 &&
         Number.isInteger(value.reserve) && value.reserve >= 0 &&
         value.stations.every(x => typeof x.station_id === 'string' && x.station_id && Number.isInteger(x.bikes) &&
           Number.isInteger(x.capacity) && x.capacity > 0 && x.bikes >= 0 && x.bikes <= x.capacity) &&
         new Set(value.stations.map(x => x.station_id)).size === value.stations.length)
      : value.as_of === null && value.reserve === null && value.stations.length === 0))
}
