import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { artifactUrl } from '../api'
import type { AnalysisResult } from '../types'
import { getOverlayClipWidth, type ViewMode } from './canvasView'
import { isColoredPixel } from './colorMask'

export type EditorTool = 'pan' | 'remove' | 'preserve' | 'erase'

interface Point {
  x: number
  y: number
}

type MaskTool = Exclude<EditorTool, 'pan'>

interface Stroke {
  tool: MaskTool
  points: Point[]
  width: number
}

interface ColorRemoval {
  tool: 'remove-color'
  mask: HTMLCanvasElement
}

type EditAction = Stroke | ColorRemoval

interface Masks {
  removeMask: string
  preserveMask: string
}

export interface EditorCanvasHandle {
  getMasks: () => Masks
  refreshResult: (
    cleanedUrl: string,
    appliedRemoveMask: string,
    appliedPreserveMask: string,
  ) => Promise<void>
  removeColoredPixels: () => boolean
  undo: () => void
  redo: () => void
}

interface EditorCanvasProps {
  analysis: AnalysisResult
  tool: EditorTool
  brushSize: number
  viewMode: ViewMode
  splitPosition: number
  overlaysVisible: boolean
  zoom: number
  onHistoryChange: (state: { canUndo: boolean; canRedo: boolean; dirty: boolean }) => void
  onMasksChange: (masks: Masks) => void
}

function loadImage(path: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('페이지 이미지를 불러오지 못했습니다.'))
    image.src = path.startsWith('data:') ? path : artifactUrl(path)
  })
}

function resizeCanvas(canvas: HTMLCanvasElement, width: number, height: number): void {
  canvas.width = width
  canvas.height = height
}

function drawStroke(canvas: HTMLCanvasElement, stroke: Stroke, draw: boolean): void {
  const context = canvas.getContext('2d')
  if (!context || stroke.points.length === 0) return
  context.save()
  context.globalCompositeOperation = draw ? 'source-over' : 'destination-out'
  context.strokeStyle = '#ffffff'
  context.fillStyle = '#ffffff'
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.lineWidth = stroke.width
  const first = stroke.points[0]
  if (stroke.points.length === 1) {
    context.beginPath()
    context.arc(first.x, first.y, stroke.width / 2, 0, Math.PI * 2)
    context.fill()
  } else {
    context.beginPath()
    context.moveTo(first.x, first.y)
    for (const point of stroke.points.slice(1)) context.lineTo(point.x, point.y)
    context.stroke()
  }
  context.restore()
}

function createColorMask(source: CanvasImageSource, width: number, height: number): HTMLCanvasElement | null {
  const mask = document.createElement('canvas')
  resizeCanvas(mask, width, height)
  const context = mask.getContext('2d')
  if (!context) return null
  context.drawImage(source, 0, 0, width, height)
  const pixels = context.getImageData(0, 0, width, height)
  let coloredPixelCount = 0
  for (let index = 0; index < pixels.data.length; index += 4) {
    if (isColoredPixel(pixels.data[index], pixels.data[index + 1], pixels.data[index + 2])) {
      pixels.data[index] = 255
      pixels.data[index + 1] = 255
      pixels.data[index + 2] = 255
      pixels.data[index + 3] = 255
      coloredPixelCount += 1
    } else {
      pixels.data[index] = 0
      pixels.data[index + 1] = 0
      pixels.data[index + 2] = 0
      pixels.data[index + 3] = 0
    }
  }
  if (coloredPixelCount === 0) return null
  context.putImageData(pixels, 0, 0)
  return mask
}

function applyColorRemoval(
  remove: HTMLCanvasElement,
  preserve: HTMLCanvasElement,
  action: ColorRemoval,
): void {
  const removeContext = remove.getContext('2d')
  const preserveContext = preserve.getContext('2d')
  if (!removeContext || !preserveContext) return
  removeContext.save()
  removeContext.globalCompositeOperation = 'source-over'
  removeContext.drawImage(action.mask, 0, 0, remove.width, remove.height)
  removeContext.restore()
  preserveContext.save()
  preserveContext.globalCompositeOperation = 'destination-out'
  preserveContext.drawImage(action.mask, 0, 0, preserve.width, preserve.height)
  preserveContext.restore()
}

const EditorCanvas = forwardRef<EditorCanvasHandle, EditorCanvasProps>(function EditorCanvas(
  {
    analysis,
    tool,
    brushSize,
    viewMode,
    splitPosition,
    overlaysVisible,
    zoom,
    onHistoryChange,
    onMasksChange,
  },
  ref,
) {
  const [initialAnalysis] = useState(analysis)
  const displayRef = useRef<HTMLCanvasElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const removeRef = useRef(document.createElement('canvas'))
  const preserveRef = useRef(document.createElement('canvas'))
  const tintRef = useRef(document.createElement('canvas'))
  const resultRef = useRef(document.createElement('canvas'))
  const workRef = useRef(document.createElement('canvas'))
  const imagesRef = useRef<Record<string, HTMLImageElement>>({})
  const baseMasksRef = useRef<{ remove: HTMLImageElement; preserve: HTMLImageElement } | null>(null)
  const appliedRemoveRef = useRef<HTMLImageElement | null>(null)
  const editsRef = useRef<EditAction[]>([])
  const historyIndexRef = useRef(0)
  const activeStrokeRef = useRef<Stroke | null>(null)
  const panRef = useRef<{
    pointerId: number
    clientX: number
    clientY: number
    scrollLeft: number
    scrollTop: number
  } | null>(null)
  const [loading, setLoading] = useState(true)
  const [panning, setPanning] = useState(false)
  const [imageRevision, setImageRevision] = useState(0)

  const getMasks = useCallback(
    (): Masks => ({
      removeMask: removeRef.current.toDataURL('image/png'),
      preserveMask: preserveRef.current.toDataURL('image/png'),
    }),
    [],
  )

  const notifyHistory = useCallback(() => {
    onHistoryChange({
      canUndo: historyIndexRef.current > 0,
      canRedo: historyIndexRef.current < editsRef.current.length,
      dirty: false,
    })
  }, [onHistoryChange])

  const tintMask = useCallback(
    (target: CanvasRenderingContext2D, mask: CanvasImageSource, color: string, alpha: number) => {
      const tint = tintRef.current
      const tintContext = tint.getContext('2d')
      if (!tintContext) return
      tintContext.clearRect(0, 0, tint.width, tint.height)
      tintContext.globalCompositeOperation = 'source-over'
      tintContext.drawImage(mask, 0, 0, tint.width, tint.height)
      tintContext.globalCompositeOperation = 'source-in'
      tintContext.fillStyle = color
      tintContext.fillRect(0, 0, tint.width, tint.height)
      tintContext.globalCompositeOperation = 'source-over'
      target.save()
      target.globalAlpha = alpha
      target.drawImage(tint, 0, 0)
      target.restore()
    },
    [],
  )

  const buildLiveResult = useCallback((): HTMLCanvasElement | null => {
    const source = imagesRef.current.source
    const cleaned = imagesRef.current.cleaned
    const appliedRemove = appliedRemoveRef.current
    const result = resultRef.current
    const resultContext = result.getContext('2d')
    const work = workRef.current
    const workContext = work.getContext('2d')
    if (!source || !cleaned || !appliedRemove || !resultContext || !workContext) return null

    resultContext.globalCompositeOperation = 'source-over'
    resultContext.clearRect(0, 0, result.width, result.height)
    resultContext.drawImage(cleaned, 0, 0, result.width, result.height)

    workContext.globalCompositeOperation = 'source-over'
    workContext.clearRect(0, 0, work.width, work.height)
    workContext.drawImage(source, 0, 0, work.width, work.height)
    workContext.globalCompositeOperation = 'destination-in'
    workContext.drawImage(appliedRemove, 0, 0, work.width, work.height)
    workContext.globalCompositeOperation = 'destination-out'
    workContext.drawImage(removeRef.current, 0, 0, work.width, work.height)
    resultContext.drawImage(work, 0, 0)

    workContext.globalCompositeOperation = 'source-over'
    workContext.clearRect(0, 0, work.width, work.height)
    workContext.fillStyle = '#ffffff'
    workContext.fillRect(0, 0, work.width, work.height)
    workContext.globalCompositeOperation = 'destination-in'
    workContext.drawImage(removeRef.current, 0, 0, work.width, work.height)
    workContext.globalCompositeOperation = 'destination-out'
    workContext.drawImage(appliedRemove, 0, 0, work.width, work.height)
    resultContext.drawImage(work, 0, 0)

    workContext.globalCompositeOperation = 'source-over'
    workContext.clearRect(0, 0, work.width, work.height)
    workContext.drawImage(source, 0, 0, work.width, work.height)
    workContext.globalCompositeOperation = 'destination-in'
    workContext.drawImage(preserveRef.current, 0, 0, work.width, work.height)
    resultContext.drawImage(work, 0, 0)
    workContext.globalCompositeOperation = 'source-over'
    return result
  }, [])

  const render = useCallback(() => {
    const canvas = displayRef.current
    const source = imagesRef.current.source
    const result = buildLiveResult()
    if (!canvas || !source || !result) return
    const context = canvas.getContext('2d')
    if (!context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    if (viewMode === 'original') {
      context.drawImage(source, 0, 0, canvas.width, canvas.height)
    } else if (viewMode === 'result') {
      context.drawImage(result, 0, 0, canvas.width, canvas.height)
    } else {
      context.drawImage(source, 0, 0, canvas.width, canvas.height)
      const boundary = Math.round(canvas.width * splitPosition)
      context.save()
      context.beginPath()
      context.rect(boundary, 0, canvas.width - boundary, canvas.height)
      context.clip()
      context.drawImage(result, 0, 0, canvas.width, canvas.height)
      context.restore()
      context.fillStyle = '#ffffff'
      context.fillRect(boundary - 1, 0, 2, canvas.height)
      context.fillStyle = '#14211d'
      context.fillRect(boundary, 0, 1, canvas.height)
    }
    const overlayClipWidth = getOverlayClipWidth(viewMode, canvas.width, splitPosition)
    if (overlaysVisible && overlayClipWidth > 0) {
      context.save()
      context.beginPath()
      context.rect(0, 0, overlayClipWidth, canvas.height)
      context.clip()
      tintMask(context, removeRef.current, '#e04b3f', 0.5)
      tintMask(context, preserveRef.current, '#00a6a6', 0.38)
      context.restore()
    }
  }, [buildLiveResult, overlaysVisible, splitPosition, tintMask, viewMode])

  const replayEdits = useCallback(() => {
    const base = baseMasksRef.current
    if (!base) return
    const remove = removeRef.current
    const preserve = preserveRef.current
    const removeContext = remove.getContext('2d')
    const preserveContext = preserve.getContext('2d')
    if (!removeContext || !preserveContext) return
    removeContext.clearRect(0, 0, remove.width, remove.height)
    preserveContext.clearRect(0, 0, preserve.width, preserve.height)
    removeContext.drawImage(base.remove, 0, 0, remove.width, remove.height)
    preserveContext.drawImage(base.preserve, 0, 0, preserve.width, preserve.height)
    for (const stroke of editsRef.current.slice(0, historyIndexRef.current)) {
      if (stroke.tool === 'remove-color') {
        applyColorRemoval(remove, preserve, stroke)
        continue
      }
      if (stroke.tool === 'remove') {
        drawStroke(remove, stroke, true)
        drawStroke(preserve, stroke, false)
      } else if (stroke.tool === 'preserve') {
        drawStroke(preserve, stroke, true)
        drawStroke(remove, stroke, false)
      } else {
        drawStroke(remove, stroke, false)
        drawStroke(preserve, stroke, false)
      }
    }
    render()
    notifyHistory()
  }, [notifyHistory, render])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      loadImage(initialAnalysis.source_url),
      loadImage(initialAnalysis.cleaned_url),
      loadImage(initialAnalysis.remove_mask_url),
      loadImage(initialAnalysis.preserve_mask_url),
    ])
      .then(([source, cleaned, remove, preserve]) => {
        if (cancelled) return
        imagesRef.current = { source, cleaned }
        baseMasksRef.current = { remove, preserve }
        appliedRemoveRef.current = remove
        const canvases = [
          displayRef.current,
          removeRef.current,
          preserveRef.current,
          tintRef.current,
          resultRef.current,
          workRef.current,
        ]
        for (const canvas of canvases) {
          if (canvas) resizeCanvas(canvas, initialAnalysis.pixel_width, initialAnalysis.pixel_height)
        }
        const removeContext = removeRef.current.getContext('2d')
        const preserveContext = preserveRef.current.getContext('2d')
        removeContext?.drawImage(remove, 0, 0, removeRef.current.width, removeRef.current.height)
        preserveContext?.drawImage(
          preserve,
          0,
          0,
          preserveRef.current.width,
          preserveRef.current.height,
        )
        editsRef.current = []
        historyIndexRef.current = 0
        setImageRevision((value) => value + 1)
        setLoading(false)
        notifyHistory()
      })
      .catch(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [initialAnalysis, notifyHistory])

  useEffect(() => render(), [imageRevision, render])

  const commitMaskChange = useCallback(() => {
    onMasksChange(getMasks())
  }, [getMasks, onMasksChange])

  const removeColoredPixels = useCallback((): boolean => {
    const source = imagesRef.current.source
    if (loading || !source) return false
    const mask = createColorMask(source, removeRef.current.width, removeRef.current.height)
    if (!mask) return false
    editsRef.current = editsRef.current.slice(0, historyIndexRef.current)
    editsRef.current.push({ tool: 'remove-color', mask })
    historyIndexRef.current = editsRef.current.length
    replayEdits()
    commitMaskChange()
    return true
  }, [commitMaskChange, loading, replayEdits])

  useImperativeHandle(
    ref,
    () => ({
      getMasks,
      refreshResult: async (
        cleanedUrl: string,
        appliedRemoveMask: string,
        appliedPreserveMask: string,
      ) => {
        const [cleaned, remove, preserve] = await Promise.all([
          loadImage(cleanedUrl),
          loadImage(appliedRemoveMask),
          loadImage(appliedPreserveMask),
        ])
        imagesRef.current.cleaned = cleaned
        appliedRemoveRef.current = remove
        if (historyIndexRef.current === 0) {
          baseMasksRef.current = { remove, preserve }
          const removeContext = removeRef.current.getContext('2d')
          const preserveContext = preserveRef.current.getContext('2d')
          removeContext?.clearRect(0, 0, removeRef.current.width, removeRef.current.height)
          preserveContext?.clearRect(0, 0, preserveRef.current.width, preserveRef.current.height)
          removeContext?.drawImage(remove, 0, 0, removeRef.current.width, removeRef.current.height)
          preserveContext?.drawImage(
            preserve,
            0,
            0,
            preserveRef.current.width,
            preserveRef.current.height,
          )
        }
        setImageRevision((value) => value + 1)
      },
      removeColoredPixels,
      undo: () => {
        if (historyIndexRef.current === 0) return
        historyIndexRef.current -= 1
        replayEdits()
        commitMaskChange()
      },
      redo: () => {
        if (historyIndexRef.current >= editsRef.current.length) return
        historyIndexRef.current += 1
        replayEdits()
        commitMaskChange()
      },
    }),
    [commitMaskChange, getMasks, removeColoredPixels, replayEdits],
  )

  const pointFromEvent = (event: ReactPointerEvent<HTMLCanvasElement>): Point => {
    const canvas = event.currentTarget
    const bounds = canvas.getBoundingClientRect()
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * canvas.width,
      y: ((event.clientY - bounds.top) / bounds.height) * canvas.height,
    }
  }

  const applyActiveStroke = (): void => {
    const stroke = activeStrokeRef.current
    if (!stroke) return
    replayEdits()
    if (stroke.tool === 'remove') {
      drawStroke(removeRef.current, stroke, true)
      drawStroke(preserveRef.current, stroke, false)
    } else if (stroke.tool === 'preserve') {
      drawStroke(preserveRef.current, stroke, true)
      drawStroke(removeRef.current, stroke, false)
    } else {
      drawStroke(removeRef.current, stroke, false)
      drawStroke(preserveRef.current, stroke, false)
    }
    render()
  }

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>): void => {
    if (loading) return
    if (viewMode !== 'original' && tool !== 'pan') return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    if (tool === 'pan') {
      const scroll = scrollRef.current
      if (!scroll) return
      panRef.current = {
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        scrollLeft: scroll.scrollLeft,
        scrollTop: scroll.scrollTop,
      }
      setPanning(true)
      return
    }
    const bounds = event.currentTarget.getBoundingClientRect()
    const scale = event.currentTarget.width / Math.max(bounds.width, 1)
    activeStrokeRef.current = {
      tool,
      points: [pointFromEvent(event)],
      width: brushSize * scale,
    }
    applyActiveStroke()
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>): void => {
    const pan = panRef.current
    const scroll = scrollRef.current
    if (pan && scroll && pan.pointerId === event.pointerId) {
      scroll.scrollLeft = pan.scrollLeft - (event.clientX - pan.clientX)
      scroll.scrollTop = pan.scrollTop - (event.clientY - pan.clientY)
      return
    }
    if (!activeStrokeRef.current || event.buttons === 0) return
    activeStrokeRef.current.points.push(pointFromEvent(event))
    applyActiveStroke()
  }

  const handlePointerUp = (event: ReactPointerEvent<HTMLCanvasElement>): void => {
    if (panRef.current?.pointerId === event.pointerId) {
      panRef.current = null
      setPanning(false)
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
      return
    }
    const stroke = activeStrokeRef.current
    if (!stroke) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    editsRef.current = editsRef.current.slice(0, historyIndexRef.current)
    editsRef.current.push(stroke)
    historyIndexRef.current = editsRef.current.length
    activeStrokeRef.current = null
    replayEdits()
    commitMaskChange()
  }

  return (
    <div ref={scrollRef} className="canvas-scroll" aria-busy={loading}>
      {loading && <div className="canvas-loading">페이지 준비 중</div>}
      <canvas
        ref={displayRef}
        className={`editor-canvas ${tool === 'pan' ? 'pan-mode' : ''} ${panning ? 'panning' : ''}`}
        style={{ width: `${zoom}%` }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        aria-label={`PDF ${initialAnalysis.page.index + 1}페이지 마스크 편집기`}
      />
    </div>
  )
})

export default EditorCanvas
