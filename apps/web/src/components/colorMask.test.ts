import { describe, expect, it } from 'vitest'
import { isColoredPixel } from './colorMask'

describe('isColoredPixel', () => {
  it('keeps black, gray, and low-saturation paper pixels', () => {
    expect(isColoredPixel(0, 0, 0)).toBe(false)
    expect(isColoredPixel(80, 80, 80)).toBe(false)
    expect(isColoredPixel(248, 245, 242)).toBe(false)
  })

  it('selects saturated dark and light colors', () => {
    expect(isColoredPixel(210, 25, 30)).toBe(true)
    expect(isColoredPixel(20, 45, 130)).toBe(true)
    expect(isColoredPixel(255, 220, 180)).toBe(true)
  })
})
