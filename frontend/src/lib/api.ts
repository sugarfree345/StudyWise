/** 与 FastAPI 后端的通信层，路径见 backend/app/api/routes。 */

const API_BASE = '/api'

export interface DocumentInfo {
  id: number
  project_id: number
  filename: string
  page_count: number
  summary: string
  table_of_contents: string
  created_at: string
  parse_status: 'pending' | 'processing' | 'ready' | 'failed'
  processed_pages: number
  parse_error: string | null
}

export interface ProjectInfo {
  id: number
  name: string
  summary: string
  document_ids: number[]
  created_at: string
  updated_at: string
}

export interface PageInfo {
  id: number
  document_id: number
  page_number: number
  summary: string
  text: string
  markdown: string
  image_ids: number[]
  render_available: boolean
}

export interface ImageInfo {
  id: number
  page_id: number | null
  document_id: number
  page_number: number
  image_index: number
  filename: string
  mime_type: string
  summary: string
  is_useful: boolean | null
  importance: number
  retrieval_count: number
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

export function listProjects() {
  return request<ProjectInfo[]>('/projects')
}

export function createProject(name: string, summary = '') {
  return request<ProjectInfo>('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, summary }),
  })
}

export function listProjectDocuments(projectId: number) {
  return request<DocumentInfo[]>(`/projects/${projectId}/documents`)
}

export function uploadProjectDocument(projectId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<DocumentInfo>(`/projects/${projectId}/documents`, {
    method: 'POST',
    body: form,
  })
}

export function reparseDocument(id: number) {
  return request<DocumentInfo>(`/documents/${id}/reparse`, { method: 'POST' })
}

/** 删除文档（含源文件与解析产物）。后端返回 204，无响应体。 */
export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(`请求失败 ${res.status}：${await res.text()}`)
  }
}

export function getPageText(documentId: number, pageNumber: number) {
  return request<PageText>(`/documents/${documentId}/pages/${pageNumber}/text`)
}

export function listPages(documentId: number) {
  return request<PageInfo[]>(`/documents/${documentId}/pages`)
}

export function getPage(documentId: number, pageNumber: number) {
  return request<PageInfo>(`/documents/${documentId}/pages/${pageNumber}`)
}

export function listPageImages(documentId: number, pageNumber: number) {
  return request<ImageInfo[]>(
    `/documents/${documentId}/pages/${pageNumber}/images`,
  )
}

export function imageFileUrl(imageId: number) {
  return `${API_BASE}/images/${imageId}`
}

/** PDF 原文件地址，左侧窗格直接加载。 */
export function documentFileUrl(documentId: number) {
  return `${API_BASE}/documents/${documentId}/file`
}

// ── LLM 对话 ────────────────────────────────────────────

export interface ModelProfile {
  name: string
  style: 'openai' | 'anthropic'
  model_id: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** 已配置的模型档案（不含 api_key）。 */
export function listModels() {
  return request<ModelProfile[]>('/models')
}

export interface ChatUsage {
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  total_tokens: number
}

export interface SavedChatMessage extends ChatMessage {
  request_content?: string | null
  input_tokens?: number | null
  output_tokens?: number | null
  cached_tokens?: number | null
  total_tokens?: number | null
}

export interface ConversationSummary {
  id: number
  document_id: number
  title: string
  profile: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends ConversationSummary {
  messages: SavedChatMessage[]
}

export function listConversations(documentId: number) {
  return request<ConversationSummary[]>(`/documents/${documentId}/conversations`)
}

export function createConversation(documentId: number, profile: string, title: string) {
  return request<ConversationSummary>(`/documents/${documentId}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, title }),
  })
}

export function getConversation(documentId: number, conversationId: number) {
  return request<ConversationDetail>(`/documents/${documentId}/conversations/${conversationId}`)
}

export function saveConversation(
  documentId: number,
  conversationId: number,
  profile: string,
  title: string,
  messages: SavedChatMessage[],
) {
  return request<ConversationSummary>(`/documents/${documentId}/conversations/${conversationId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, title, messages }),
  })
}

type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }
  | ({ type: 'usage' } & ChatUsage)

function parseSseEvent(chunk: string): ChatEvent | null {
  const line = chunk.split(/\r?\n/).find((item) => item.startsWith('data: '))
  return line ? (JSON.parse(line.slice(6)) as ChatEvent) : null
}

/**
 * 对整本文档发起流式提问，全文共用一段对话。后端返回 SSE，逐个吐出 ChatEvent。
 * 后端无状态：每次把完整对话历史 messages 带上；currentPage 只用于标注当前浏览位置。
 */
export async function* streamChat(
  documentId: number,
  currentPage: number,
  profile: string,
  messages: ChatMessage[],
): AsyncGenerator<ChatEvent> {
  const res = await fetch(
    `${API_BASE}/documents/${documentId}/chat?page=${currentPage}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile, messages }),
    },
  )
  if (!res.ok || !res.body) {
    throw new Error(`请求失败 ${res.status}：${await res.text()}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split(/\r?\n\r?\n/)
    buffer = chunks.pop() ?? '' // 最后一段可能不完整，留到下一轮
    for (const chunk of chunks) {
      const event = parseSseEvent(chunk)
      if (event) yield event
    }
  }
  buffer += decoder.decode()
  const finalEvent = parseSseEvent(buffer)
  if (finalEvent) yield finalEvent
}
