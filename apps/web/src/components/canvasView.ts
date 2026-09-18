export type ViewMode = 'original' | 'result' | 'split'

export function getOverlayClipWidth(
  viewMode: ViewMode,
  canvasWidth: number,
  splitPosition: number,
): number {
  if (viewMode === 'result') return 0
  if (viewMode === 'split') return Math.round(canvasWidth * splitPosition)
  return canvasWidth
}
