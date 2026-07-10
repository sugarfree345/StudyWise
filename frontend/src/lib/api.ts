/** 与 FastAPI 后端的通信层，路径见 backend/app/api/routes。 */

const API_BASE = '/api'

export interface DocumentInfo {
  id: number
  filename: string
  stored_path: string
  page_count: number
  created_at: string
}

export interface PageText {
  page_number: number
  text: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`请求失败 ${res.status}：${detail}`)
  }
  return res.json() as Promise<T>
}

export function listDocuments() {
  return request<DocumentInfo[]>('/documents')
}

export function getDocument(id: number) {
  return request<DocumentInfo>(`/documents/${id}`)
}

export function uploadDocument(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<DocumentInfo>('/documents', { method: 'POST', body: form })
}

export function getPageText(documentId: number, pageNumber: number) {
  return request<PageText>(`/documents/${documentId}/pages/${pageNumber}/text`)
}

/** PDF 原文件地址，左侧窗格直接加载。 */
export function documentFileUrl(documentId: number) {
  return `${API_BASE}/documents/${documentId}/file`
}
