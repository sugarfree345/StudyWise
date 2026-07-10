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

type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

function parseSseEvent(chunk: string): ChatEvent | null {
  const line = chunk.split(/\r?\n/).find((item) => item.startsWith('data: '))
  return line ? (JSON.parse(line.slice(6)) as ChatEvent) : null
}

/**
 * 对当前页发起流式提问。后端返回 SSE，这里解析成 ChatEvent 逐个吐出。
 * 后端无状态：每次把完整对话历史 messages 带上。
 */
export async function* streamChat(
  documentId: number,
  pageNumber: number,
  profile: string,
  messages: ChatMessage[],
): AsyncGenerator<ChatEvent> {
  const res = await fetch(
    `${API_BASE}/documents/${documentId}/pages/${pageNumber}/chat`,
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
