import { describe, expect, it } from 'vitest'
import { hourOf, paletteAt } from './daylight.js'

describe('daylight palette', () => {
  it('reads the hour from a reading time', () => {
    expect(hourOf('2026-10-19T18:15')).toBe(18.25)
    expect(hourOf('06:00')).toBe(6)
    expect(hourOf(undefined)).toBe(12)
  })
  it('is dark at night, light at midday, and blends in between', () => {
    expect(paletteAt(3)).toMatchObject({ phase: 'night', bg: '#07090c', light: false })
    expect(paletteAt(13)).toMatchObject({ phase: 'midday', bg: '#dbe3e8', light: true })
    expect(paletteAt(19).phase).toBe('sunset')
    const between = paletteAt(15)
    expect(between.bg).not.toBe(paletteAt(13).bg)
    expect(between.bg).not.toBe(paletteAt(17).bg)
  })
  it('sunlight is strongest at midday and weakest at night', () => {
    expect(paletteAt(13).sunI).toBeGreaterThan(paletteAt(19).sunI)
    expect(paletteAt(19).sunI).toBeGreaterThan(paletteAt(23).sunI)
  })
})
