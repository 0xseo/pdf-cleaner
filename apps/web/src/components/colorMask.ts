export const COLOR_SATURATION_THRESHOLD = 35
export const COLOR_CHROMA_THRESHOLD = 20

export function isColoredPixel(red: number, green: number, blue: number): boolean {
  const maximum = Math.max(red, green, blue)
  const minimum = Math.min(red, green, blue)
  const chroma = maximum - minimum
  if (maximum === 0 || chroma < COLOR_CHROMA_THRESHOLD) return false
  return (chroma / maximum) * 255 >= COLOR_SATURATION_THRESHOLD
}
