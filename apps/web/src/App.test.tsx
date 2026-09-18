import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const editorActions = vi.hoisted(() => ({
  undo: vi.fn(),
  redo: vi.fn(),
}))

vi.mock('./components/EditorCanvas', async () => {
  const React = await import('react')
  return {
    default: React.forwardRef(function MockEditorCanvas(
      props: { onMasksChange: (masks: { removeMask: string; preserveMask: string }) => void },
      ref: React.ForwardedRef<unknown>,
    ) {
      React.useImperativeHandle(ref, () => ({
        getMasks: () => ({ removeMask: 'remove', preserveMask: 'preserve' }),
        refreshResult: async () => undefined,
        removeColoredPixels: () => true,
        undo: editorActions.undo,
        redo: editorActions.redo,
      }))
      return (
        <button
          type="button"
          onClick={() =>
            props.onMasksChange({
              removeMask: 'data:image/png;base64,remove',
              preserveMask: 'data:image/png;base64,preserve',
            })
          }
        >
          보존 획 테스트
        </button>
      )
    }),
  }
})

const page = {
  index: 0,
  width_points: 595,
  height_points: 842,
  media_box: [0, 0, 595, 842],
  crop_box: [0, 0, 595, 842],
  rotation: 0,
  annotation_count: 0,
  ink_annotation_count: 0,
  text_character_count: 0,
  status: 'ready',
  risk_level: 'review',
  risk_score: 0.4,
  error: null,
}

const analysis = {
  page,
  pixel_width: 1000,
  pixel_height: 1400,
  dpi: 300,
  candidate_ratio: 0.02,
  automatic_remove_ratio: 0.02,
  preserve_ratio: 0.1,
  pdf_text_regions: 0,
  ocr_text_regions: 20,
  structural_line_regions: 5,
  revision: 1,
  source_url: '/source',
  cleaned_url: '/cleaned',
  candidate_mask_url: '/candidate',
  remove_mask_url: '/remove',
  preserve_mask_url: '/preserve',
  review_mask_url: '/review',
}

describe('App', () => {
  beforeEach(() => {
    editorActions.undo.mockClear()
    editorActions.redo.mockClear()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'ok' }) }),
    )
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('opens on the real PDF upload workspace', async () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'PDF 필기 지우개' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'PDF 또는 작업 파일 놓기' })).toBeInTheDocument()
    expect(screen.getByText('작업 파일 열기')).toBeInTheDocument()
    expect(screen.queryByText(/이 컴퓨터의 로컬 엔진에서만/)).not.toBeInTheDocument()
    expect(await screen.findByText('로컬 엔진 연결됨')).toBeInTheDocument()
  })

  it('opens a dropped PDF file', async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/health')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response
      }
      if (url.endsWith('/api/jobs') && init?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 'job-drop',
            display_name: 'dropped.pdf',
            source_sha256: 'hash',
            page_count: 1,
            created_at: '2026-09-18T00:00:00Z',
            pages: [{ ...page, status: 'pending' }],
          }),
        } as Response
      }
      if (url.endsWith('/pages/0/analyze')) {
        return { ok: true, status: 200, json: async () => analysis } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { container } = render(<App />)
    await screen.findByText('로컬 엔진 연결됨')
    const dropZone = container.querySelector('.upload-zone')
    expect(dropZone).not.toBeNull()
    fireEvent.dragEnter(dropZone!)
    expect(dropZone).toHaveClass('dragging')
    fireEvent.drop(dropZone!, {
      dataTransfer: { files: [new File(['pdf'], 'dropped.pdf', { type: 'application/pdf' })] },
    })

    expect(await screen.findByRole('button', { name: '보존 획 테스트' })).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/jobs',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('opens a dropped local project file', async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/health')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response
      }
      if (url.endsWith('/api/projects') && init?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 'job-project',
            display_name: 'resumed.pdf',
            source_sha256: 'hash',
            page_count: 1,
            created_at: '2026-09-18T00:00:00Z',
            pages: [{ ...page, status: 'ready' }],
          }),
        } as Response
      }
      if (url.endsWith('/pages/0/analyze')) {
        return { ok: true, status: 200, json: async () => analysis } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { container } = render(<App />)
    await screen.findByText('로컬 엔진 연결됨')
    const dropZone = container.querySelector('.upload-zone')
    fireEvent.drop(dropZone!, {
      dataTransfer: {
        files: [
          new File(['project'], 'resumed.pdferaser', {
            type: 'application/vnd.pdf-eraser+zip',
          }),
        ],
      },
    })

    expect(await screen.findByRole('button', { name: '보존 획 테스트' })).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8000/api/projects',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('edits a completed page during analysis and applies masks without a save button', async () => {
    const pendingSecondPage = new Promise<Response>(() => undefined)
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/health')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response
      }
      if (url.endsWith('/api/jobs') && init?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 'job-1',
            display_name: 'sample.pdf',
            source_sha256: 'hash',
            page_count: 2,
            created_at: '2026-09-18T00:00:00Z',
            pages: [
              { ...page, status: 'pending' },
              { ...page, index: 1, status: 'pending' },
            ],
          }),
        } as Response
      }
      if (url.endsWith('/pages/0/analyze')) {
        return { ok: true, status: 200, json: async () => analysis } as Response
      }
      if (url.endsWith('/pages/1/analyze')) return pendingSecondPage
      if (url.endsWith('/pages/0/mask')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ...analysis, revision: 2 }),
        } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { container } = render(<App />)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    expect(input).not.toBeNull()
    fireEvent.change(input!, {
      target: { files: [new File(['pdf'], 'sample.pdf', { type: 'application/pdf' })] },
    })

    expect(await screen.findByRole('button', { name: '보존 획 테스트' })).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /현재 페이지 저장/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'PDF로 내보내기' })).toBeInTheDocument()
    expect(screen.queryByText(/구조 보존 Overlay|보안 평탄화 PDF/)).not.toBeInTheDocument()

    const editorPanel = container.querySelector('.editor-panel')
    expect(editorPanel).toHaveClass('has-split-control')
    expect(screen.getByRole('button', { name: '제거' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '보존' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '지우개' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '색상 전체 제거' })).toBeDisabled()
    expect(screen.getByRole('slider', { name: /^크기/ })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: '제거' }))
    expect(screen.getByRole('button', { name: '원본' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '제거' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '색상 전체 제거' })).toBeEnabled()
    const brushSlider = screen.getByRole('slider', { name: /^크기/ })
    fireEvent.change(brushSlider, { target: { value: '44' } })
    expect(screen.getByText('44 px')).toBeInTheDocument()
    expect(container.querySelector('.brush-size-preview-ring')).toHaveStyle({
      width: '44px',
      height: '44px',
    })

    fireEvent.click(screen.getByRole('button', { name: '결과' }))
    expect(editorPanel).not.toHaveClass('has-split-control')
    expect(screen.getByRole('button', { name: '제거' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '색상 전체 제거' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '제거' })).toHaveClass('active')

    fireEvent.click(screen.getByRole('button', { name: '보존' }))
    expect(screen.getByRole('button', { name: '원본' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '보존' })).toHaveClass('active')

    fireEvent.keyDown(window, { key: 'f' })
    expect(screen.getByRole('button', { name: '결과' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '보존' })).toHaveClass('active')
    fireEvent.keyDown(window, { key: 'r' })
    expect(screen.getByRole('button', { name: '원본' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '제거' })).toHaveClass('active')
    fireEvent.keyDown(window, { key: 'c' })
    expect(screen.getByRole('button', { name: '비교' })).toHaveClass('active')
    expect(screen.getByRole('button', { name: '제거' })).toHaveClass('active')
    fireEvent.keyDown(window, { key: 'o' })
    fireEvent.keyDown(window, { key: 'm' })
    expect(screen.getByRole('button', { name: '이동' })).toHaveClass('active')

    fireEvent.keyDown(window, { key: 'z', metaKey: true })
    fireEvent.keyDown(window, { key: 'z', metaKey: true, shiftKey: true })
    expect(editorActions.undo).toHaveBeenCalledTimes(1)
    expect(editorActions.redo).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: '보존 획 테스트' }))
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/api/jobs/job-1/pages/0/mask',
        expect.objectContaining({ method: 'PATCH' }),
      )
    })
    expect(screen.queryByText('검수')).not.toBeInTheDocument()
    expect(screen.queryByText(/자동 적용/)).not.toBeInTheDocument()
    expect(screen.queryByText('PDF 텍스트')).not.toBeInTheDocument()
    expect(screen.queryByText('OCR 위치 힌트')).not.toBeInTheDocument()
    expect(screen.queryByText('구조선')).not.toBeInTheDocument()
    expect(screen.queryByText('기본 제거 후보')).not.toBeInTheDocument()
    expect(screen.queryByText(/가려진 원본 내용/)).not.toBeInTheDocument()
    expect(screen.queryByText(/검수 권장|위험도/)).not.toBeInTheDocument()
  })

  it('shows progress inside the export button while creating a PDF', async () => {
    let finishExport: ((response: Response) => void) | undefined
    const pendingExport = new Promise<Response>((resolve) => {
      finishExport = resolve
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.endsWith('/api/health')) {
        return { ok: true, status: 200, json: async () => ({ status: 'ok' }) } as Response
      }
      if (url.endsWith('/api/jobs') && init?.method === 'POST') {
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 'job-export',
            display_name: 'sample.pdf',
            source_sha256: 'hash',
            page_count: 1,
            created_at: '2026-09-18T00:00:00Z',
            pages: [{ ...page, status: 'pending' }],
          }),
        } as Response
      }
      if (url.endsWith('/pages/0/analyze')) {
        return { ok: true, status: 200, json: async () => analysis } as Response
      }
      if (url.endsWith('/export')) return pendingExport
      if (url.endsWith('/project')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            filename: 'sample.pdferaser',
            download_url: '/download-project/sample.pdferaser',
          }),
        } as Response
      }
      throw new Error(`Unexpected request: ${url}`)
    })

    const { container } = render(<App />)
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    fireEvent.change(input!, {
      target: { files: [new File(['pdf'], 'sample.pdf', { type: 'application/pdf' })] },
    })
    const exportButton = await screen.findByRole('button', { name: 'PDF로 내보내기' })
    await waitFor(() => expect(exportButton).toBeEnabled())
    fireEvent.click(exportButton)

    const busyButton = screen.getByRole('button', { name: 'PDF 만드는 중' })
    expect(busyButton).toHaveAttribute('aria-busy', 'true')
    expect(busyButton.querySelector('.spin')).not.toBeNull()

    finishExport?.({
      ok: true,
      status: 200,
      json: async () => ({
        mode: 'overlay',
        filename: 'sample_cleaned.pdf',
        download_url: '/download/sample_cleaned.pdf',
        validated: true,
        validation_report: {},
      }),
    } as Response)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'PDF로 내보내기' })).toBeEnabled()
    })

    fireEvent.click(screen.getByRole('button', { name: '작업 파일 저장' }))
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/api/jobs/job-export/project',
        expect.objectContaining({ method: 'POST' }),
      )
    })
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(2)
  })
})
