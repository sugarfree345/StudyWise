import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Check, CircleAlert, LoaderCircle, Plus, Send, Trash2, Wrench } from 'lucide-react'

import Markdown from '@/components/study/Markdown'
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  listModels,
  saveConversation,
  streamChat,
  type ChatActivity,
  type ChatContextUsage,
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
 * ``content`` 只用于界面展示；``requestContent`` 用一个紧凑标签记录消息发送时
 * 的界面页码，供模型解析指代与规划工具调用，同时保持历史前缀不可变。
 */
type ChatEntry = ChatMessage & {
  id: string
  requestContent?: string
  usage?: ChatUsage
  contextUsage?: ChatContextUsage
  activityTrace?: ChatActivity[]
  durationMs?: number
  startedAt?: number
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.max(0, milliseconds) / 1000
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

function formatTokens(tokens: number): string {
  if (tokens < 1_000) return tokens.toLocaleString()
  if (tokens < 1_000_000) return `${(tokens / 1_000).toFixed(tokens < 10_000 ? 1 : 0)}k`
  return `${(tokens / 1_000_000).toFixed(1)}M`
}

function ContextRing({ context }: { context?: ChatContextUsage }) {
  const windowSize = context?.context_window ?? 128_000
  const used = context?.context_tokens ?? 0
  const percent = Math.min(100, (used / windowSize) * 100)
  const radius = 15
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - percent / 100)
  return (
    <div
      className="flex items-center gap-2"
      title={`本轮请求开始前的上下文估算：${used.toLocaleString()} / ${windowSize.toLocaleString()} tokens`}
    >
      <svg viewBox="0 0 36 36" className="size-9 -rotate-90" aria-label={`上下文窗口已使用 ${percent.toFixed(1)}%`}>
        <circle cx="18" cy="18" r={radius} fill="none" stroke="currentColor" strokeWidth="3" className="text-muted" />
        <circle
          cx="18"
          cy="18"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className={percent >= 90 ? 'text-destructive' : percent >= 70 ? 'text-amber-500' : 'text-primary'}
        />
      </svg>
      <div className="leading-tight">
        <p className="text-xs font-medium tabular-nums">Context {percent.toFixed(percent < 10 ? 1 : 0)}%</p>
        <p className="text-[11px] tabular-nums text-muted-foreground">{formatTokens(used)} / {formatTokens(windowSize)}</p>
      </div>
    </div>
  )
}

function ActivityTrace({
  activities,
  active,
  startedAt,
  durationMs,
  now,
}: {
  activities: ChatActivity[]
  active: boolean
  startedAt?: number
  durationMs?: number
  now: number
}) {
  const [expanded, setExpanded] = useState(false)
  const elapsed = durationMs ?? (startedAt ? now - startedAt : 0)
  return (
    <details
      className="group mb-1.5 w-[85%] text-xs text-muted-foreground"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md px-1 py-0.5 transition-colors hover:bg-muted [&::-webkit-details-marker]:hidden">
        {active ? <LoaderCircle className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
        <span className="tabular-nums">{active ? 'Working' : 'Worked'} for {formatDuration(elapsed)}</span>
        {activities.some((item) => item.kind === 'tool_call') && (
          <span>· {activities.filter((item) => item.kind === 'tool_call').length} 次工具调用</span>
        )}
      </summary>
      {expanded && <div className="mt-1.5 space-y-2 border-l border-border pl-3">
        {activities.map((activity, activityIndex) => {
          if (activity.kind === 'status') {
            return <p key={activityIndex}>{activity.message}</p>
          }
          if (activity.kind === 'tool_call') {
            return (
              <div key={activityIndex} className="rounded-md border border-border bg-background/70 p-2">
                <p className="flex items-center gap-1.5 font-medium text-foreground">
                  <Wrench className="size-3.5" /> 调用 {activity.tool}
                </p>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-relaxed">
                  {JSON.stringify(activity.arguments, null, 2)}
                </pre>
              </div>
            )
          }
          return (
            <div key={activityIndex} className="rounded-md border border-border bg-background/70 p-2">
              <p className={`flex items-center gap-1.5 font-medium ${activity.is_error ? 'text-destructive' : 'text-foreground'}`}>
                {activity.is_error ? <CircleAlert className="size-3.5" /> : <Check className="size-3.5" />}
                {activity.tool} 返回
                {activity.has_image && ' · 含图片'}
                {activity.truncated && ` · 已截断（${activity.result_chars.toLocaleString()} 字符）`}
              </p>
              {activity.result && (
                <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed">
                  {activity.result}
                </pre>
              )}
            </div>
          )
        })}
      </div>}
    </details>
  )
}

function withPageContext(question: string, page: number): string {
  return `${question}\n\n[ui_page=${page}]`
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
    context_tokens: message.contextUsage?.context_tokens,
    context_window: message.contextUsage?.context_window,
    activity_trace: message.activityTrace,
    duration_ms: message.durationMs,
  }
}

function fromSavedMessage(message: SavedChatMessage, id: string): ChatEntry {
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
  const contextUsage =
    message.context_tokens == null || message.context_window == null
      ? undefined
      : {
          context_tokens: message.context_tokens,
          context_window: message.context_window,
        }
  return {
    id,
    role: message.role,
    content: message.content,
    requestContent: message.request_content ?? undefined,
    usage,
    contextUsage,
    activityTrace: message.activity_trace ?? undefined,
    durationMs: message.duration_ms ?? undefined,
  }
}

const MessageBubble = memo(function MessageBubble({
  message,
  active,
  now,
}: {
  message: ChatEntry
  active: boolean
  now: number
}) {
  return (
    <div className={message.role === 'user' ? 'flex justify-end' : 'flex flex-col items-start'}>
      {message.role === 'assistant' && (message.activityTrace || message.startedAt || message.durationMs != null) && (
        <ActivityTrace
          activities={message.activityTrace ?? []}
          active={active}
          startedAt={message.startedAt}
          durationMs={message.durationMs}
          now={now}
        />
      )}
      {(message.role === 'user' || message.content) && (
        <div className={message.role === 'user' ? 'max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground' : 'max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm'}>
          {message.role === 'user' ? message.content : <Markdown>{message.content}</Markdown>}
        </div>
      )}
      {message.role === 'assistant' && message.usage && (
        <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
          {message.usage.total_tokens.toLocaleString()} tokens（输入 {message.usage.input_tokens.toLocaleString()} · 输出 {message.usage.output_tokens.toLocaleString()}
          {message.usage.cached_tokens > 0 && ` · 缓存 ${message.usage.cached_tokens.toLocaleString()}`}）
        </p>
      )}
    </div>
  )
})

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
  const [clock, setClock] = useState(() => Date.now())
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const entrySequenceRef = useRef(0)
  const scrollFrameRef = useRef<number | null>(null)
  const assistantFrameRef = useRef<number | null>(null)
  const pendingAssistantUpdateRef = useRef<Partial<ChatEntry> | null>(null)
  // 仅在用户仍停留在底部附近时跟随流式输出；手动上滑后不再抢回滚动位置。
  const followLatestRef = useRef(true)
  const docReady = doc.parse_status === 'ready'
  const createEntryId = useCallback(
    () => `${doc.id}-${Date.now()}-${++entrySequenceRef.current}`,
    [doc.id],
  )
  const getScrollElement = useCallback(() => scrollRef.current, [])
  const estimateMessageSize = useCallback(() => 180, [])
  const rowVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement,
    estimateSize: estimateMessageSize,
    getItemKey: (index) => messages[index]?.id ?? index,
    overscan: 4,
  })
  const conversationTotalTokens = messages.reduce(
    (total, message) => total + (message.usage?.total_tokens ?? 0),
    0,
  )
  const latestContextUsage = [...messages].reverse().find((message) => message.contextUsage)?.contextUsage

  useEffect(() => {
    if (!models.some((model) => model.name === selectedProfile)) {
      const fallback = models[0]?.name ?? null
      if (selectedProfile !== fallback) setSelectedProfile(fallback)
    }
  }, [models, selectedProfile, setSelectedProfile])

  const scheduleScrollToBottom = useCallback(() => {
    if (!followLatestRef.current || scrollFrameRef.current !== null) return
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null
      const container = scrollRef.current
      if (container && followLatestRef.current) container.scrollTop = container.scrollHeight
    })
  }, [])

  useEffect(() => {
    scheduleScrollToBottom()
  }, [messages, scheduleScrollToBottom])

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current)
    if (assistantFrameRef.current !== null) window.cancelAnimationFrame(assistantFrameRef.current)
  }, [])

  useEffect(() => {
    if (!streaming) return
    setClock(Date.now())
    const timer = window.setInterval(() => setClock(Date.now()), 100)
    return () => window.clearInterval(timer)
  }, [streaming])

  function updateFollowLatest() {
    const container = scrollRef.current
    if (!container) return
    // 留一点容差，避免子像素布局使用户已经在底部却被误判。
    followLatestRef.current =
      container.scrollHeight - container.scrollTop - container.clientHeight < 48
  }

  function scheduleAssistantUpdate(update: Partial<ChatEntry>) {
    pendingAssistantUpdateRef.current = {
      ...pendingAssistantUpdateRef.current,
      ...update,
    }
    if (assistantFrameRef.current !== null) return
    assistantFrameRef.current = window.requestAnimationFrame(() => {
      assistantFrameRef.current = null
      const pending = pendingAssistantUpdateRef.current
      pendingAssistantUpdateRef.current = null
      if (!pending) return
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { ...next[next.length - 1], ...pending, role: 'assistant' }
        return next
      })
    })
  }

  function cancelPendingAssistantUpdate() {
    if (assistantFrameRef.current !== null) {
      window.cancelAnimationFrame(assistantFrameRef.current)
      assistantFrameRef.current = null
    }
    pendingAssistantUpdateRef.current = null
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
      setMessages(conversation.messages.map((message) => fromSavedMessage(message, createEntryId())))
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

  async function removeCurrentConversation() {
    if (conversationId === null || streaming) return
    if (!window.confirm('确定删除当前对话吗？此操作不可恢复。')) return

    try {
      await deleteConversation(doc.id, conversationId)
      startNewConversation()
      await queryClient.invalidateQueries({ queryKey: ['conversations', doc.id] })
    } catch (e) {
      setError(`对话删除失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  async function send() {
    const question = input.trim()
    if (!question || streaming || !selectedProfile || !docReady) return

    // 发送新问题是用户主动要求查看最新内容，恢复自动跟随。
    followLatestRef.current = true
    const requestContent = withPageContext(question, currentPage)
    const userEntry: ChatEntry = { id: createEntryId(), role: 'user', content: question, requestContent }
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

    const startedAt = Date.now()
    const assistantEntry: ChatEntry = {
      id: createEntryId(),
      role: 'assistant',
      content: '',
      activityTrace: [],
      startedAt,
    }
    const initialEntries = [
      ...messages,
      userEntry,
      assistantEntry,
    ]
    setMessages(initialEntries)
    setInput('')
    setStreaming(true)
    setError(null)

    let answer = ''
    let usage: ChatUsage | undefined
    let contextUsage: ChatContextUsage | undefined
    let activityTrace: ChatActivity[] = []
    let durationMs: number | undefined
    try {
      for await (const ev of streamChat(
        doc.id,
        currentPage,
        selectedProfile,
        history,
        activeConversationId,
      )) {
        if (ev.type === 'delta') {
          answer += ev.text
          scheduleAssistantUpdate({ content: answer })
        } else if (ev.type === 'activity') {
          activityTrace = [...activityTrace, ev.activity]
          scheduleAssistantUpdate({ activityTrace })
        } else if (ev.type === 'usage') {
          usage = ev
          scheduleAssistantUpdate({ usage })
        } else if (ev.type === 'context') {
          contextUsage = ev
          scheduleAssistantUpdate({ contextUsage })
        } else if (ev.type === 'done') {
          durationMs = ev.duration_ms
          scheduleAssistantUpdate({ durationMs })
        } else if (ev.type === 'error') {
          durationMs = ev.duration_ms ?? Date.now() - startedAt
          setError(ev.message)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      cancelPendingAssistantUpdate()
      durationMs ??= Date.now() - startedAt
      const savedEntries: ChatEntry[] = answer || activityTrace.length > 0
        ? [...messages, userEntry, { ...assistantEntry, content: answer, usage, contextUsage, activityTrace, durationMs }]
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
        <button
          type="button"
          aria-label="删除当前对话"
          title="删除当前对话"
          disabled={streaming || conversationId === null}
          onClick={() => void removeCurrentConversation()}
          className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
        >
          <Trash2 className="size-4" />
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

      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <p className="text-xs tabular-nums text-muted-foreground">
          本对话累计 <span className="font-medium text-foreground">{conversationTotalTokens.toLocaleString()}</span> tokens
        </p>
        <ContextRing context={latestContextUsage} />
      </div>

      <div ref={scrollRef} onScroll={updateFollowLatest} className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {docReady ? '选择已有对话，或开始一段新对话。' : '文档正在进行 OCR 解析，完成后即可提问。'}
          </p>
        )}
        {messages.length > 0 && (
          <div
            className="relative w-full"
            style={{ height: `${rowVirtualizer.getTotalSize()}px` }}
          >
            {rowVirtualizer.getVirtualItems().map((virtualRow) => {
              const message = messages[virtualRow.index]
              const active = streaming && virtualRow.index === messages.length - 1
              return (
                <div
                  key={message.id}
                  data-index={virtualRow.index}
                  ref={rowVirtualizer.measureElement}
                  className="absolute left-0 top-0 w-full pb-4"
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                >
                  <MessageBubble message={message} active={active} now={active ? clock : 0} />
                </div>
              )
            })}
          </div>
        )}
        {error && <p className="text-sm text-destructive">出错了：{error}</p>}
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={!docReady}
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
