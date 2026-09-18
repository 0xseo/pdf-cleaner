import { useCallback, useEffect, useRef, useState, type DragEvent as ReactDragEvent } from 'react'
import {
  AlertTriangle,
  Brush,
  ChevronLeft,
  ChevronRight,
  Download,
  Eraser,
  Eye,
  EyeOff,
  FolderOpen,
  FileUp,
  Hand,
  LoaderCircle,
  Maximize2,
  Palette,
  Pencil,
  Redo2,
  Save,
  Shield,
  Trash2,
  Undo2,
  Wifi,
  WifiOff,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import {
  analyzePage,
  artifactUrl,
  checkHealth,
  deleteJob,
  exportPdf,
  exportProject,
  saveMasks,
  uploadPdf,
  uploadProject,
} from './api'
import EditorCanvas, {
  type EditorCanvasHandle,
  type EditorTool,
} from './components/EditorCanvas'
import type { ViewMode } from './components/canvasView'
import type { AnalysisResult, JobInfo, ProjectExportResult } from './types'

interface HistoryState {
  canUndo: boolean
  canRedo: boolean
  dirty: boolean
}

const initialHistory: HistoryState = { canUndo: false, canRedo: false, dirty: false }

const toolShortcuts: Record<EditorTool, string> = {
  pan: 'M',
  remove: 'R',
  preserve: 'P',
  erase: 'E',
}

const viewShortcuts: Record<ViewMode, string> = {
  original: 'O',
  split: 'C',
  result: 'F',
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

function downloadArtifact(result: ProjectExportResult | { filename: string; download_url: string }): void {
  const anchor = document.createElement('a')
  anchor.href = artifactUrl(result.download_url)
  anchor.download = result.filename
  anchor.click()
}

function App() {
  const editorRef = useRef<EditorCanvasHandle>(null)
  const runIdRef = useRef(0)
  const activeJobIdRef = useRef<string | null>(null)
  const selectedPageRef = useRef(0)
  const maskSaveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const brushPreviewTimerRef = useRef<number | null>(null)
  const [engineOnline, setEngineOnline] = useState<boolean | null>(null)
  const [job, setJob] = useState<JobInfo | null>(null)
  const [analyses, setAnalyses] = useState<Record<number, AnalysisResult>>({})
  const [selectedPage, setSelectedPage] = useState(0)
  const [processedPages, setProcessedPages] = useState(0)
  const [analysisInProgress, setAnalysisInProgress] = useState(false)
  const [applyingCount, setApplyingCount] = useState(0)
  const [busyLabel, setBusyLabel] = useState('')
  const [isExporting, setIsExporting] = useState(false)
  const [isSavingProject, setIsSavingProject] = useState(false)
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [brushPreviewVisible, setBrushPreviewVisible] = useState(false)
  const [error, setError] = useState('')
  const [tool, setTool] = useState<EditorTool>('pan')
  const [brushSize, setBrushSize] = useState(26)
  const [viewMode, setViewMode] = useState<ViewMode>('split')
  const [splitPosition, setSplitPosition] = useState(0.5)
  const [overlaysVisible, setOverlaysVisible] = useState(true)
  const [zoom, setZoom] = useState(100)
  const [history, setHistory] = useState<HistoryState>(initialHistory)

  useEffect(() => {
    void checkHealth().then(setEngineOnline)
  }, [])

  useEffect(() => {
    selectedPageRef.current = selectedPage
  }, [selectedPage])

  useEffect(() => () => {
    if (brushPreviewTimerRef.current !== null) {
      window.clearTimeout(brushPreviewTimerRef.current)
    }
  }, [])

  const setAnalysis = useCallback((analysis: AnalysisResult) => {
    setAnalyses((current) => ({ ...current, [analysis.page.index]: analysis }))
    setJob((current) => {
      if (!current) return current
      const pages = [...current.pages]
      pages[analysis.page.index] = analysis.page
      return { ...current, pages }
    })
  }, [])

  const analyzeSequentially = useCallback(
    async (newJob: JobInfo, runId: number) => {
      setAnalysisInProgress(true)
      for (const page of newJob.pages) {
        if (runIdRef.current !== runId) return
        try {
          const analysis = await analyzePage(newJob.id, page.index)
          if (runIdRef.current !== runId) return
          setAnalysis(analysis)
          setProcessedPages((value) => value + 1)
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : '페이지 분석에 실패했습니다.')
          break
        }
      }
      if (runIdRef.current === runId) setAnalysisInProgress(false)
    },
    [setAnalysis],
  )

  const startJob = useCallback(
    (newJob: JobInfo, previousJob: JobInfo | null): void => {
      if (previousJob) void deleteJob(previousJob.id).catch(() => undefined)
      const runId = runIdRef.current + 1
      runIdRef.current = runId
      activeJobIdRef.current = newJob.id
      setJob(newJob)
      setAnalyses({})
      setSelectedPage(0)
      setProcessedPages(0)
      setHistory(initialHistory)
      setTool('pan')
      setViewMode('split')
      setBrushPreviewVisible(false)
      setBusyLabel('')
      void analyzeSequentially(newJob, runId)
    },
    [analyzeSequentially],
  )

  const handleUpload = async (file: File): Promise<void> => {
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setError('PDF 파일을 선택해 주세요.')
      return
    }
    setError('')
    setBusyLabel('PDF 검사 중')
    const previousJob = job
    try {
      const newJob = await uploadPdf(file)
      startJob(newJob, previousJob)
    } catch (cause) {
      setBusyLabel('')
      setError(cause instanceof Error ? cause.message : 'PDF를 열지 못했습니다.')
    }
  }

  const handleProjectUpload = async (file: File): Promise<void> => {
    if (!file.name.toLowerCase().endsWith('.pdferaser')) {
      setError('PDF 필기 지우개 작업 파일을 선택해 주세요.')
      return
    }
    setError('')
    setBusyLabel('작업 파일 여는 중')
    const previousJob = job
    try {
      const newJob = await uploadProject(file)
      startJob(newJob, previousJob)
    } catch (cause) {
      setBusyLabel('')
      setError(cause instanceof Error ? cause.message : '작업 파일을 열지 못했습니다.')
    }
  }

  const handleDrop = (event: ReactDragEvent<HTMLDivElement>): void => {
    event.preventDefault()
    setIsDraggingFile(false)
    if (!engineOnline) return
    const file = event.dataTransfer.files[0]
    if (!file) return
    if (file.name.toLowerCase().endsWith('.pdferaser')) void handleProjectUpload(file)
    else void handleUpload(file)
  }

  const queueMaskUpdate = useCallback(
    (masks: { removeMask: string; preserveMask: string }): void => {
      if (!job || !analyses[selectedPage]) return
      const jobId = job.id
      const pageIndex = selectedPage
      setApplyingCount((value) => value + 1)
      maskSaveQueueRef.current = maskSaveQueueRef.current
        .catch(() => undefined)
        .then(async () => {
          if (activeJobIdRef.current !== jobId) return
          const updated = await saveMasks(
            jobId,
            pageIndex,
            masks.removeMask,
            masks.preserveMask,
          )
          if (activeJobIdRef.current !== jobId) return
          setAnalysis(updated)
          if (selectedPageRef.current === pageIndex) {
            await editorRef.current?.refreshResult(
              updated.cleaned_url,
              masks.removeMask,
              masks.preserveMask,
            )
          }
        })
        .catch((cause: unknown) => {
          setError(cause instanceof Error ? cause.message : '수정 결과를 적용하지 못했습니다.')
        })
        .finally(() => {
          setApplyingCount((value) => Math.max(0, value - 1))
        })
    },
    [analyses, job, selectedPage, setAnalysis],
  )

  const moveToPage = async (nextPage: number): Promise<void> => {
    if (!job || nextPage < 0 || nextPage >= job.page_count || nextPage === selectedPage) return
    if (!analyses[nextPage]) return
    setSelectedPage(nextPage)
    setHistory(initialHistory)
  }

  const selectTool = useCallback((nextTool: EditorTool): void => {
    setTool(nextTool)
    if (nextTool === 'pan') setBrushPreviewVisible(false)
    if (nextTool !== 'pan') setViewMode('original')
  }, [])

  const changeViewMode = useCallback((mode: ViewMode): void => {
    setViewMode(mode)
    if (mode !== 'original') setBrushPreviewVisible(false)
  }, [])

  const updateBrushSize = (value: number): void => {
    setBrushSize(value)
    setBrushPreviewVisible(true)
    if (brushPreviewTimerRef.current !== null) {
      window.clearTimeout(brushPreviewTimerRef.current)
    }
    brushPreviewTimerRef.current = window.setTimeout(() => {
      setBrushPreviewVisible(false)
      brushPreviewTimerRef.current = null
    }, 800)
  }

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent): void => {
      if (!activeJobIdRef.current || event.isComposing || isEditableTarget(event.target)) return
      const key = event.key.toLowerCase()
      if ((event.metaKey || event.ctrlKey) && !event.altKey && key === 'z') {
        event.preventDefault()
        if (event.shiftKey) editorRef.current?.redo()
        else editorRef.current?.undo()
        return
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const toolByKey: Record<string, EditorTool> = {
        m: 'pan',
        r: 'remove',
        p: 'preserve',
        e: 'erase',
      }
      const viewByKey: Record<string, ViewMode> = {
        o: 'original',
        c: 'split',
        f: 'result',
      }
      if (toolByKey[key]) {
        event.preventDefault()
        selectTool(toolByKey[key])
      } else if (viewByKey[key]) {
        event.preventDefault()
        changeViewMode(viewByKey[key])
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [changeViewMode, selectTool])

  const handleExport = async (): Promise<void> => {
    if (!job) return
    setError('')
    setIsExporting(true)
    setBusyLabel('PDF 검증 중')
    try {
      await maskSaveQueueRef.current
      const result = await exportPdf(job.id)
      downloadArtifact(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'PDF 내보내기에 실패했습니다.')
    } finally {
      setBusyLabel('')
      setIsExporting(false)
    }
  }

  const handleProjectSave = async (): Promise<void> => {
    if (!job) return
    setError('')
    setIsSavingProject(true)
    setBusyLabel('작업 파일 만드는 중')
    try {
      await maskSaveQueueRef.current
      const result = await exportProject(job.id)
      downloadArtifact(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '작업 파일 저장에 실패했습니다.')
    } finally {
      setBusyLabel('')
      setIsSavingProject(false)
    }
  }

  const handleClose = async (): Promise<void> => {
    runIdRef.current += 1
    setAnalysisInProgress(false)
    await maskSaveQueueRef.current.catch(() => undefined)
    if (job) await deleteJob(job.id).catch(() => undefined)
    activeJobIdRef.current = null
    setJob(null)
    setAnalyses({})
    setBusyLabel('')
    setIsExporting(false)
    setIsSavingProject(false)
    setBrushPreviewVisible(false)
    setError('')
  }

  const currentAnalysis = analyses[selectedPage]
  const progress = job ? Math.round((processedPages / job.page_count) * 100) : 0

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">
            <Pencil className="brand-pencil" size={18} />
            <Eraser className="brand-eraser" size={13} />
          </span>
          <h1>PDF 필기 지우개</h1>
          <span className="version">LOCAL</span>
        </div>
        <div className={`engine-status ${engineOnline ? 'online' : 'offline'}`}>
          {engineOnline ? <Wifi size={15} /> : <WifiOff size={15} />}
          {engineOnline === null ? '확인 중' : engineOnline ? '로컬 엔진 연결됨' : '로컬 엔진 연결 필요'}
        </div>
        {job && (
          <button className="icon-button" title="현재 작업 닫기" onClick={() => void handleClose()}>
            <Trash2 size={17} />
          </button>
        )}
      </header>

      {!job ? (
        <section className="empty-workspace">
          <div
            className={`upload-zone ${isDraggingFile ? 'dragging' : ''}`}
            onDragEnter={(event) => {
              event.preventDefault()
              if (engineOnline) setIsDraggingFile(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setIsDraggingFile(false)
              }
            }}
            onDrop={handleDrop}
          >
            <FileUp size={32} aria-hidden="true" />
            <h2>PDF 또는 작업 파일 놓기</h2>
            <div className="upload-actions">
              <label className="primary-button">
                <FileUp size={17} />
                PDF 열기
                <input
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void handleUpload(file)
                  }}
                  disabled={!engineOnline}
                />
              </label>
              <label className="secondary-button">
                <FolderOpen size={17} />
                작업 파일 열기
                <input
                  type="file"
                  accept=".pdferaser,application/vnd.pdf-eraser+zip"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) void handleProjectUpload(file)
                  }}
                  disabled={!engineOnline}
                />
              </label>
            </div>
          </div>
        </section>
      ) : (
        <section className="workspace">
          <aside className="page-sidebar" aria-label="페이지 목록">
            <div className="panel-heading">
              <span>페이지</span>
              <span>{processedPages}/{job.page_count}</span>
            </div>
            {analysisInProgress && (
              <div className="progress-track" aria-label={`분석 ${progress}%`}>
                <span style={{ width: `${progress}%` }} />
              </div>
            )}
            <div className="thumbnail-list">
              {job.pages.map((page) => {
                const analysis = analyses[page.index]
                return (
                  <button
                    key={page.index}
                    className={`thumbnail-item ${selectedPage === page.index ? 'selected' : ''}`}
                    onClick={() => void moveToPage(page.index)}
                    title={`${page.index + 1}페이지`}
                    disabled={!analysis}
                  >
                    <span className="thumb-image">
                      {analysis ? (
                        <img src={artifactUrl(analysis.source_url)} alt="" />
                      ) : page.status === 'error' ? (
                        <AlertTriangle size={20} />
                      ) : (
                        <LoaderCircle className="spin" size={18} />
                      )}
                    </span>
                    <span className="thumb-meta">
                      <strong>{page.index + 1}</strong>
                      <span className={`risk-dot ${page.risk_level}`} />
                    </span>
                  </button>
                )
              })}
            </div>
          </aside>

          <section className={`editor-panel ${viewMode === 'split' ? 'has-split-control' : ''}`}>
            <div className="toolbar" aria-label="마스크 편집 도구">
              <div className="tool-group segmented">
                <button aria-label="이동" className={tool === 'pan' ? 'active' : ''} onClick={() => selectTool('pan')} title="화면 이동 (M)">
                  <Hand size={17} /><span>이동</span><kbd className="shortcut-key" aria-hidden="true">{toolShortcuts.pan}</kbd>
                </button>
                <button aria-label="제거" className={tool === 'remove' ? 'active' : ''} onClick={() => selectTool('remove')} title="제거 브러시 (R)">
                  <Brush size={17} /><span>제거</span><kbd className="shortcut-key" aria-hidden="true">{toolShortcuts.remove}</kbd>
                </button>
                <button aria-label="보존" className={tool === 'preserve' ? 'active' : ''} onClick={() => selectTool('preserve')} title="보존 브러시 (P)">
                  <Shield size={17} /><span>보존</span><kbd className="shortcut-key" aria-hidden="true">{toolShortcuts.preserve}</kbd>
                </button>
                <button aria-label="지우개" className={tool === 'erase' ? 'active' : ''} onClick={() => selectTool('erase')} title="마스크 지우개 (E)">
                  <Eraser size={17} /><span>지우개</span><kbd className="shortcut-key" aria-hidden="true">{toolShortcuts.erase}</kbd>
                </button>
              </div>
              <label className="brush-control">
                <span>크기</span>
                <input type="range" min="6" max="80" value={brushSize} disabled={viewMode !== 'original' || tool === 'pan'} onChange={(event) => updateBrushSize(Number(event.target.value))} />
                <output>{brushSize}</output>
              </label>
              <button
                className="icon-text-button"
                disabled={viewMode !== 'original'}
                title="현재 페이지의 모든 색상 픽셀 제거 (색상 인쇄물 포함)"
                onClick={() => {
                  setError('')
                  if (!editorRef.current?.removeColoredPixels()) {
                    setError('제거할 색상 픽셀을 찾지 못했습니다.')
                  }
                }}
              >
                <Palette size={17} /><span>색상 전체 제거</span>
              </button>
              <div className="tool-group">
                <button aria-label="실행 취소" className="icon-shortcut-button" title="실행 취소 (Cmd/Ctrl+Z)" disabled={!history.canUndo} onClick={() => editorRef.current?.undo()}><Undo2 size={17} /><kbd className="shortcut-key" aria-hidden="true">⌘Z</kbd></button>
                <button aria-label="다시 실행" className="icon-shortcut-button" title="다시 실행 (Cmd/Ctrl+Shift+Z)" disabled={!history.canRedo} onClick={() => editorRef.current?.redo()}><Redo2 size={17} /><kbd className="shortcut-key" aria-hidden="true">⇧⌘Z</kbd></button>
              </div>
              <div className="toolbar-spacer" />
              <div className="tool-group segmented view-segment">
                {(['original', 'split', 'result'] as ViewMode[]).map((mode) => (
                  <button key={mode} aria-label={mode === 'original' ? '원본' : mode === 'split' ? '비교' : '결과'} className={viewMode === mode ? 'active' : ''} onClick={() => changeViewMode(mode)}>
                    <span>{mode === 'original' ? '원본' : mode === 'split' ? '비교' : '결과'}</span>
                    <kbd className="shortcut-key" aria-hidden="true">{viewShortcuts[mode]}</kbd>
                  </button>
                ))}
              </div>
              <button
                className="icon-button"
                title={viewMode === 'result' ? '결과 화면에서는 오버레이 숨김' : overlaysVisible ? '오버레이 숨기기' : '오버레이 표시'}
                disabled={viewMode === 'result'}
                onClick={() => setOverlaysVisible((value) => !value)}
              >
                {overlaysVisible ? <Eye size={17} /> : <EyeOff size={17} />}
              </button>
              <button className="icon-button" title="축소" onClick={() => setZoom((value) => Math.max(40, value - 20))}><ZoomOut size={17} /></button>
              <button className="icon-button" title="맞춤" onClick={() => setZoom(100)}><Maximize2 size={17} /></button>
              <button className="icon-button" title="확대" onClick={() => setZoom((value) => Math.min(240, value + 20))}><ZoomIn size={17} /></button>
            </div>
            {viewMode === 'split' && (
              <label className="split-control">
                <span>원본</span>
                <input type="range" min="5" max="95" value={splitPosition * 100} onChange={(event) => setSplitPosition(Number(event.target.value) / 100)} />
                <span>결과</span>
              </label>
            )}
            <div className="canvas-stage">
              {brushPreviewVisible && viewMode === 'original' && tool !== 'pan' && (
                <div className="brush-size-preview" aria-live="polite">
                  <span
                    className="brush-size-preview-ring"
                    style={{ width: brushSize, height: brushSize }}
                  />
                  <output>{brushSize} px</output>
                </div>
              )}
              {currentAnalysis ? (
                <EditorCanvas
                  key={selectedPage}
                  ref={editorRef}
                  analysis={currentAnalysis}
                  tool={viewMode === 'original' ? tool : 'pan'}
                  brushSize={brushSize}
                  viewMode={viewMode}
                  splitPosition={splitPosition}
                  overlaysVisible={overlaysVisible}
                  zoom={zoom}
                  onHistoryChange={setHistory}
                  onMasksChange={queueMaskUpdate}
                />
              ) : (
                <div className="page-wait"><LoaderCircle className="spin" size={24} /> 페이지를 순차 분석하고 있습니다.</div>
              )}
            </div>
            <footer className="page-nav">
              <button className="icon-text-button" disabled={selectedPage === 0 || !analyses[selectedPage - 1]} onClick={() => void moveToPage(selectedPage - 1)}><ChevronLeft size={17} /> 이전</button>
              <span>{selectedPage + 1} / {job.page_count}</span>
              <button className="icon-text-button" disabled={selectedPage === job.page_count - 1 || !analyses[selectedPage + 1]} onClick={() => void moveToPage(selectedPage + 1)}>다음 <ChevronRight size={17} /></button>
            </footer>
          </section>

          <aside className="inspector">
            {currentAnalysis ? (
              <div className="legend">
                <span><i className="red" />기본 제거</span>
                <span><i className="cyan" />인쇄물·사용자 보존</span>
              </div>
            ) : <div className="muted">분석 대기 중</div>}
            <div className="project-section">
              <button
                className={`secondary-button full ${isSavingProject ? 'is-busy' : ''}`}
                aria-busy={isSavingProject}
                disabled={isSavingProject || isExporting || analysisInProgress || applyingCount > 0}
                onClick={() => void handleProjectSave()}
              >
                {isSavingProject ? <LoaderCircle className="spin" size={17} /> : <Save size={17} />}
                {isSavingProject ? '작업 파일 만드는 중' : '작업 파일 저장'}
              </button>
            </div>
            <div className="export-section">
              <h2>내보내기</h2>
              <button aria-busy={isExporting} className={`primary-button full ${isExporting ? 'is-busy' : ''}`} disabled={isExporting || isSavingProject || analysisInProgress || applyingCount > 0} onClick={() => void handleExport()}>
                {isExporting ? <LoaderCircle className="spin" size={17} /> : <Download size={17} />}
                {isExporting ? 'PDF 만드는 중' : 'PDF로 내보내기'}
              </button>
            </div>
          </aside>
        </section>
      )}

      {(busyLabel || error) && (
        <div className={`status-toast ${error ? 'error' : ''}`} role="status">
          {error ? <AlertTriangle size={17} /> : <LoaderCircle className="spin" size={17} />}
          <span>{error || busyLabel}</span>
          {error && <button className="icon-button" title="오류 닫기" onClick={() => setError('')}><EyeOff size={15} /></button>}
        </div>
      )}
    </main>
  )
}

export default App
