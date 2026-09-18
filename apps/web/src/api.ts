import type { AnalysisResult, ExportResult, JobInfo, ProjectExportResult } from './types'

export const ENGINE_URL = (import.meta.env.VITE_ENGINE_URL as string | undefined) ?? 'http://127.0.0.1:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${ENGINE_URL}${path}`, init)
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new Error(payload?.detail ?? `요청 실패 (${response.status})`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return response.json() as Promise<T>
}

export function artifactUrl(path: string): string {
  return `${ENGINE_URL}${path}`
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request<{ status: string }>('/api/health')
    return true
  } catch {
    return false
  }
}

export function uploadPdf(file: File): Promise<JobInfo> {
  const form = new FormData()
  form.append('file', file)
  return request<JobInfo>('/api/jobs', { method: 'POST', body: form })
}

export function uploadProject(file: File): Promise<JobInfo> {
  const form = new FormData()
  form.append('file', file)
  return request<JobInfo>('/api/projects', { method: 'POST', body: form })
}

export function analyzePage(jobId: string, pageIndex: number): Promise<AnalysisResult> {
  return request<AnalysisResult>(`/api/jobs/${jobId}/pages/${pageIndex}/analyze`, {
    method: 'POST',
  })
}

export function saveMasks(
  jobId: string,
  pageIndex: number,
  removeMask: string,
  preserveMask: string,
): Promise<AnalysisResult> {
  return request<AnalysisResult>(`/api/jobs/${jobId}/pages/${pageIndex}/mask`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ remove_mask: removeMask, preserve_mask: preserveMask }),
  })
}

export function exportPdf(jobId: string): Promise<ExportResult> {
  return request<ExportResult>(`/api/jobs/${jobId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'overlay' }),
  })
}

export function exportProject(jobId: string): Promise<ProjectExportResult> {
  return request<ProjectExportResult>(`/api/jobs/${jobId}/project`, { method: 'POST' })
}

export function deleteJob(jobId: string): Promise<void> {
  return request<void>(`/api/jobs/${jobId}`, { method: 'DELETE' })
}
