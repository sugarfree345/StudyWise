import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Send } from 'lucide-react'

import Markdown from '@/components/study/Markdown'
import {
  createConversation,
  getConversation,
  listConversations,
  listModels,
  saveConversation,
  streamChat,
  type ChatMessage,
  type ChatUsage,
  type DocumentInfo,
  type SavedChatMessage,
} from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import { useSettingsStore } from '@/stores/useSettingsStore'
import { useStudyStore } from '@/stores/useStudyStore'

interface ChatPanelProps {
  doc: DocumentInfo
}

/**
 * ``content`` 只用于界面展示；用户消息的 ``requestContent`` 会附上提问当时的
 * 页码，并作为不可变历史发送给模型。这样下一轮请求严格以前一轮为前缀。
 */
type ChatEntry = ChatMessage & { requestContent?: string; usage?: ChatUsage }

function withPageContext(question: string, page: number): string {
  return `${question}\n\n（提问时当前第 ${page} 页；本问题中的「这一页/当前页」即指此页。）`
}

function conversationTitle(messages: ChatEntry[]): string {
  const firstQuestion = messages.find((message) => message.role === 'user')?.content.trim()
  return firstQuestion ? firstQuestion.replace(/\s+/g, ' ').slice(0, 32) : '新对话'
}

function toSavedMessage(message: ChatEntry): SavedChatMessage {
  return {
    role: message.role,
    content: message.content,
    request_content: message.requestContent,
    input_tokens: message.usage?.input_tokens,
    output_tokens: message.usage?.output_tokens,
    cached_tokens: message.usage?.cached_tokens,
    total_tokens: message.usage?.total_tokens,
  }
}

function fromSavedMessage(message: SavedChatMessage): ChatEntry {
  const usage =
    message.input_tokens == null ||
    message.output_tokens == null ||
    message.cached_tokens == null ||
    message.total_tokens == null
      ? undefined
      : {
          input_tokens: message.input_tokens,
          output_tokens: message.output_tokens,
          cached_tokens: message.cached_tokens,
          total_tokens: message.total_tokens,
        }
  return { role: message.role, content: message.content, requestContent: message.request_content ?? undefined, usage }
}

/** 针对当前页的对话面板：模型选择 + 可恢复会话 + 流式回答。 */
export default function ChatPanel({ doc }: ChatPanelProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const { selectedProfile, setSelectedProfile } = useSettingsStore()
  const { data: models = [] } = useQuery({ queryKey: ['models'], queryFn: listModels })
  const { data: conversations = [] } = useQuery({
    queryKey: ['conversations', doc.id],
    queryFn: () => listConversations(doc.id),
  })

  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  // 仅在用户仍停留在底部附近时跟随流式输出；手动上滑后不再抢回滚动位置。
  const followLatestRef = useRef(true)
  const docReady = doc.parse_status === 'ready'

  useEffect(() => {
    if (!models.some((model) => model.name === selectedProfile)) {
      const fallback = models[0]?.name ?? null
      if (selectedProfile !== fallback) setSelectedProfile(fallback)
    }
  }, [models, selectedProfile, setSelectedProfile])

  useEffect(() => {
    const container = scrollRef.current
    if (container && followLatestRef.current) {
      container.scrollTop = container.scrollHeight
    }
  }, [messages])

  function updateFollowLatest() {
    const container = scrollRef.current
    if (!container) return
    // 留一点容差，避免子像素布局使用户已经在底部却被误判。
    followLatestRef.current =
      container.scrollHeight - container.scrollTop - container.clientHeight < 48
  }

  function startNewConversation() {
    if (streaming) return
    followLatestRef.current = true
    setConversationId(null)
    setMessages([])
    setError(null)
    setInput('')
  }

  async function restoreConversation(id: number) {
    if (streaming) return
    try {
      const conversation = await getConversation(doc.id, id)
      followLatestRef.current = true
      setConversationId(conversation.id)
      setMessages(conversation.messages.map(fromSavedMessage))
      setSelectedProfile(conversation.profile)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function persist(id: number, profile: string, entries: ChatEntry[]) {
    await saveConversation(doc.id, id, profile, conversationTitle(entries), entries.map(toSavedMessage))
    await queryClient.invalidateQueries({ queryKey: ['conversations', doc.id] })
  }

  async function send() {
    const question = input.trim()
    if (!question || streaming || !selectedProfile || !docReady) return

    // 发送新问题是用户主动要求查看最新内容，恢复自动跟随。
    followLatestRef.current = true
    const requestContent = withPageContext(question, currentPage)
    const userEntry: ChatEntry = { role: 'user', content: question, requestContent }
    const history: ChatMessage[] = [
      ...messages.map(({ role, content, requestContent: savedRequestContent }) => ({
        role,
        content: savedRequestContent ?? content,
      })),
      { role: 'user', content: requestContent },
    ]

    let activeConversationId = conversationId
    try {
      if (activeConversationId === null) {
        const created = await createConversation(doc.id, selectedProfile, conversationTitle([...messages, userEntry]))
        activeConversationId = created.id
        setConversationId(created.id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return
    }

    const initialEntries = [...messages, userEntry, { role: 'assistant' as const, content: '' }]
    setMessages(initialEntries)
    setInput('')
    setStreaming(true)
    setError(null)

    let answer = ''
    let usage: ChatUsage | undefined
    try {
      for await (const ev of streamChat(doc.id, currentPage, selectedProfile, history)) {
        if (ev.type === 'delta') {
          answer += ev.text
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], role: 'assistant', content: answer }
            return next
          })
        } else if (ev.type === 'usage') {
          usage = ev
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], role: 'assistant', usage }
            return next
          })
        } else if (ev.type === 'error') {
          setError(ev.message)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      const savedEntries: ChatEntry[] = answer
        ? [...messages, userEntry, { role: 'assistant', content: answer, usage }]
        : [...messages, userEntry]
      setMessages(savedEntries)
      setStreaming(false)
      try {
        await persist(activeConversationId, selectedProfile, savedEntries)
      } catch (e) {
        setError(`对话保存失败：${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <select
          value={conversationId ?? ''}
          disabled={streaming}
          onChange={(event) => {
            const id = Number(event.target.value)
            if (id) void restoreConversation(id)
            else startNewConversation()
          }}
          aria-label="对话列表"
          className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">新对话</option>
          {conversations.map((conversation) => (
            <option key={conversation.id} value={conversation.id}>
              {conversation.title}（{conversation.profile}）
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-label="新建对话"
          title="新建对话"
          disabled={streaming}
          onClick={startNewConversation}
          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent disabled:opacity-40"
        >
          <Plus className="size-4" />
        </button>
        <span className="text-sm text-muted-foreground">模型</span>
        <select
          value={selectedProfile ?? ''}
          onChange={(event) => setSelectedProfile(event.target.value)}
          disabled={streaming}
          className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
        >
          {models.length === 0 && <option value="">未配置模型（见 models.example.json）</option>}
          {models.map((model) => (
            <option key={model.name} value={model.name}>
              {model.name}（{model.style}）
            </option>
          ))}
        </select>
      </div>

      <div ref={scrollRef} onScroll={updateFollowLatest} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {docReady ? '选择已有对话，或开始一段新对话。' : '文档正在进行 OCR 解析，完成后即可提问。'}
          </p>
        )}
        {messages.map((message, index) => (
          <div key={index} className={message.role === 'user' ? 'flex justify-end' : 'flex flex-col items-start'}>
            <div className={message.role === 'user' ? 'max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground' : 'max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm'}>
              {message.role === 'user' ? message.content : <Markdown>{message.content || '…'}</Markdown>}
            </div>
            {message.role === 'assistant' && message.usage && (
              <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
                {message.usage.total_tokens.toLocaleString()} tokens（输入 {message.usage.input_tokens.toLocaleString()} · 输出 {message.usage.output_tokens.toLocaleString()}
                {message.usage.cached_tokens > 0 && ` · 缓存 ${message.usage.cached_tokens.toLocaleString()}`}）
              </p>
            )}
          </div>
        ))}
        {error && <p className="text-sm text-destructive">出错了：{error}</p>}
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={!docReady || streaming}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send()
              }
            }}
            placeholder={docReady ? '输入问题，Enter 发送，Shift+Enter 换行' : '等待文档 OCR 解析完成'}
            rows={2}
            className="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <button onClick={() => void send()} disabled={streaming || !input.trim() || !selectedProfile || !docReady} className="rounded-md bg-primary p-2 text-primary-foreground transition-opacity disabled:opacity-40" aria-label="发送">
            <Send className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
