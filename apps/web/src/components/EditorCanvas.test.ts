import { describe, expect, it } from 'vitest'
import { getOverlayClipWidth } from './canvasView'

describe('getOverlayClipWidth', () => {
  it('keeps overlays out of result pixels', () => {
    expect(getOverlayClipWidth('result', 1000, 0.5)).toBe(0)
    expect(getOverlayClipWidth('split', 1000, 0.4)).toBe(400)
    expect(getOverlayClipWidth('original', 1000, 0.5)).toBe(1000)
  })
})
