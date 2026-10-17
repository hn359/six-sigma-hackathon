import { describe, expect, it } from 'vitest'
import { joinGap, rushWindows, windowAt } from './rush.js'

describe('rush windows on the time bar', () => {
  it('joins rush slots less than an hour apart (collegetown, 15-min readings)', () => {
    // 07:00 07:15 07:45 08:15 08:45 09:00 09:15 | 16:00 16:45 17:00 17:15 17:45 18:15 18:30
    const slots = [4, 5, 7, 9, 11, 12, 13, 40, 43, 44, 45, 47, 49, 50]
    expect(joinGap(15)).toBe(3)
    expect(rushWindows(slots, joinGap(15))).toEqual([[4, 13], [40, 50]])
  })
  it('splits at a gap of an hour or more', () => {
    expect(rushWindows([4, 8], 3)).toEqual([[4, 4], [8, 8]])
    expect(joinGap(10)).toBe(5)
  })
  it('gives no windows when there are no rush slots, and accepts unsorted or repeated slots', () => {
    expect(rushWindows([], 3)).toEqual([])
    expect(rushWindows(undefined, 3)).toEqual([])
    expect(rushWindows([9, 4, 5, 4], 3)).toEqual([[4, 5], [9, 9]])
  })
  it('finds the window a reading is in', () => {
    const w = [[4, 13], [40, 50]]
    expect(windowAt(w, 4)).toEqual([4, 13])
    expect(windowAt(w, 50)).toEqual([40, 50])
    expect(windowAt(w, 20)).toBeNull()
  })
})
