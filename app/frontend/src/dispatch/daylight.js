// Map colours by time of day: key moments of the day, blended in between.
// Only presentation: the simulated reading time picks the palette; nothing statistical.

// hour (0-24) -> palette. Night, dawn, morning, midday, golden afternoon, sunset, dusk, night.
const KEYS = [
  [0, { phase: 'night', bg: '#07090c', land: '#0c1610', park: '#0d1c13', water: '#0b2133', minor: '#1f2730', major: '#2b3642', building: '#161c23', label: '#6f7c89', sun: '#9fb4ff', sunI: 0.7, amb: 0.7 }],
  [5.5, { phase: 'night', bg: '#07090c', land: '#0c1610', park: '#0d1c13', water: '#0b2133', minor: '#1f2730', major: '#2b3642', building: '#161c23', label: '#6f7c89', sun: '#9fb4ff', sunI: 0.7, amb: 0.7 }],
  [6.75, { phase: 'dawn', bg: '#2b2236', land: '#2e3330', park: '#33402f', water: '#2d4566', minor: '#4d4558', major: '#6b5a6e', building: '#45394d', label: '#b9a8c4', sun: '#ffb38a', sunI: 1.4, amb: 0.9 }],
  [8.5, { phase: 'morning', bg: '#c7d3dc', land: '#c9d8c2', park: '#b4d0a3', water: '#93bfd9', minor: '#eef2f5', major: '#ffffff', building: '#dfe4e9', label: '#56616d', sun: '#fff4e0', sunI: 2.3, amb: 1.1 }],
  [13, { phase: 'midday', bg: '#dbe3e8', land: '#d3e0cc', park: '#bfdcab', water: '#a3cce6', minor: '#f5f7f9', major: '#ffffff', building: '#eceff2', label: '#56616d', sun: '#ffffff', sunI: 2.6, amb: 1.2 }],
  [17, { phase: 'afternoon', bg: '#e2cfae', land: '#d8d0ae', park: '#c6cc98', water: '#a2bccd', minor: '#f6eadb', major: '#fff4e3', building: '#eadbc4', label: '#6d5f4c', sun: '#ffd28a', sunI: 2.2, amb: 1.05 }],
  [19, { phase: 'sunset', bg: '#5c3a4c', land: '#4c4038', park: '#4d5236', water: '#3d5272', minor: '#7d5a66', major: '#a2737a', building: '#7a5562', label: '#e7c2bf', sun: '#ff8a4c', sunI: 1.6, amb: 0.85 }],
  [20.75, { phase: 'dusk', bg: '#161b29', land: '#151f1b', park: '#15241b', water: '#122a40', minor: '#252e3d', major: '#323d4e', building: '#222a37', label: '#7f8a9a', sun: '#a9b8ff', sunI: 0.9, amb: 0.75 }],
  [22, { phase: 'night', bg: '#07090c', land: '#0c1610', park: '#0d1c13', water: '#0b2133', minor: '#1f2730', major: '#2b3642', building: '#161c23', label: '#6f7c89', sun: '#9fb4ff', sunI: 0.7, amb: 0.7 }],
  [24, { phase: 'night', bg: '#07090c', land: '#0c1610', park: '#0d1c13', water: '#0b2133', minor: '#1f2730', major: '#2b3642', building: '#161c23', label: '#6f7c89', sun: '#9fb4ff', sunI: 0.7, amb: 0.7 }],
]

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
const toHex = (c) => '#' + c.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')
const mix = (a, b, t) => toHex(hex(a).map((v, i) => v + (hex(b)[i] - v) * t))

// "2026-10-19T18:15" or "18:15" -> hour as a number (18.25)
export function hourOf(asOf) {
  const m = /(\d{2}):(\d{2})/.exec(asOf ?? '')
  return m ? Number(m[1]) + Number(m[2]) / 60 : 12
}

export function paletteAt(hour) {
  const h = ((hour % 24) + 24) % 24
  let k = 0
  while (k < KEYS.length - 2 && KEYS[k + 1][0] <= h) k++
  const [h0, a] = KEYS[k]
  const [h1, b] = KEYS[k + 1]
  const t = h1 > h0 ? (h - h0) / (h1 - h0) : 0
  const out = { phase: t < 0.5 ? a.phase : b.phase, light: false }
  for (const key of Object.keys(a)) {
    if (key === 'phase') continue
    out[key] = typeof a[key] === 'number' ? a[key] + (b[key] - a[key]) * t : mix(a[key], b[key], t)
  }
  // light backgrounds need dark road labels with a light halo, and the other way round
  const [r, g, bl] = hex(out.bg)
  out.light = 0.299 * r + 0.587 * g + 0.114 * bl > 140
  return out
}
