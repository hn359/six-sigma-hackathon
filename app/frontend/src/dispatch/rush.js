// Rush windows for the time bar. The slots themselves come from the API (summary.rush_slots:
// readings whose usual |net flow| is at least 1.5x the day's mean, learned from week 1);
// this only joins them into continuous windows so the bar does not flicker. Nothing statistical.

// [7, 8, 10, 12, 40, 41] with maxGap 4 -> [[7, 12], [40, 41]]: slots at most maxGap apart join.
export function rushWindows(slots, maxGap) {
  const ks = [...new Set(slots ?? [])].sort((a, b) => a - b)
  const out = []
  for (const k of ks) {
    const last = out[out.length - 1]
    if (last && k - last[1] <= maxGap) last[1] = k
    else out.push([k, k])
  }
  return out
}

// Slots less than an hour apart join: 3 readings at 15 min, 5 at 10 min.
export const joinGap = (intervalMinutes) => Math.max(1, Math.ceil(60 / (intervalMinutes || 15)) - 1)

export const windowAt = (windows, k) => windows.find(([a, b]) => a <= k && k <= b) ?? null
