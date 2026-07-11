import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Trash2 } from 'lucide-react'

import Markdown from '@/components/study/Markdown'
import {
  listModels,
  streamChat,
  type ChatMessage,
  type ChatUsage,
  type DocumentInfo,
} from '@/lib/api'
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

/** 针对当前页的对话面板：模型选择 + 流式回答 + Markdown 渲染。 */
export default function ChatPanel({ doc }: ChatPanelProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const { selectedProfile, setSelectedProfile } = useSettingsStore()

  const { data: models = [] } = useQuery({ queryKey: ['models'], queryFn: listModels })

  const [messages, setMessages] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const docReady = doc.parse_status === 'ready'

  // 首次使用或本地保存的档案已被删除时，选中第一个可用模型
  useEffect(() => {
    if (!models.some((model) => model.name === selectedProfile)) {
      const fallback = models[0]?.name ?? null
      if (selectedProfile !== fallback) setSelectedProfile(fallback)
    }
  }, [models, selectedProfile, setSelectedProfile])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [messages])

  async function send() {
    const question = input.trim()
    if (!question || streaming || !selectedProfile || !docReady) return

    // 每个问题在产生时就带上当前页，并永久保留在模型历史中。UI 仍只显示原问题。
    const requestContent = withPageContext(question, currentPage)
    const history: ChatMessage[] = [
      ...messages.map(({ role, content, requestContent }) => ({
        role,
        content: requestContent ?? content,
      })),
      { role: 'user', content: requestContent },
    ]
    setMessages([
      ...messages,
      { role: 'user', content: question, requestContent },
      { role: 'assistant', content: '' },
    ])
    setInput('')
    setStreaming(true)
    setError(null)

    try {
      for await (const ev of streamChat(doc.id, currentPage, selectedProfile, history)) {
        if (ev.type === 'delta') {
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = {
              ...next[next.length - 1],
              role: 'assistant',
              content: next[next.length - 1].content + ev.text,
            }
            return next
          })
        } else if (ev.type === 'usage') {
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = {
                ...last,
                usage: {
                  input_tokens: ev.input_tokens,
                  output_tokens: ev.output_tokens,
                  cached_tokens: ev.cached_tokens,
                  total_tokens: ev.total_tokens,
                },
              }
            }
            return next
          })
        } else if (ev.type === 'error') {
          setError(ev.message)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setMessages((prev) => {
        const last = prev[prev.length - 1]
        return last?.role === 'assistant' && !last.content ? prev.slice(0, -1) : prev
      })
      setStreaming(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="text-sm text-muted-foreground">模型</span>
        <select
          value={selectedProfile ?? ''}
          onChange={(e) => setSelectedProfile(e.target.value)}
          className="flex-1 rounded-md border border-border bg-background px-2 py-1 text-sm"
        >
          {models.length === 0 && <option value="">未配置模型（见 models.example.json）</option>}
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name}（{m.style}）
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-label="清空会话"
          title="清空当前会话"
          disabled={streaming || messages.length === 0}
          onClick={() => {
            setMessages([])
            setError(null)
          }}
          className="shrink-0 rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent disabled:opacity-40"
        >
          <Trash2 className="size-4" />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {docReady
              ? '就整本文档提问，或让模型出一道小测验；左侧滚动阅读不会中断对话。'
              : '文档正在进行 OCR 解析，完成后即可提问。'}
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={
              m.role === 'user' ? 'flex justify-end' : 'flex flex-col items-start'
            }
          >
            <div
              className={
                m.role === 'user'
                  ? 'max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground'
                  : 'max-w-[85%] rounded-lg bg-muted px-3 py-2 text-sm'
              }
            >
              {m.role === 'user' ? m.content : <Markdown>{m.content || '…'}</Markdown>}
            </div>
            {m.role === 'assistant' && m.usage && (
              <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
                {m.usage.total_tokens.toLocaleString()} tokens（输入{' '}
                {m.usage.input_tokens.toLocaleString()} · 输出{' '}
                {m.usage.output_tokens.toLocaleString()}
                {m.usage.cached_tokens > 0 &&
                  ` · 缓存 ${m.usage.cached_tokens.toLocaleString()}`}
                ）
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
            onChange={(e) => setInput(e.target.value)}
            disabled={!docReady}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder={
              docReady
                ? '输入问题，Enter 发送，Shift+Enter 换行'
                : '等待文档 OCR 解析完成'
            }
            rows={2}
            className="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <button
            onClick={() => void send()}
            disabled={streaming || !input.trim() || !selectedProfile || !docReady}
            className="rounded-md bg-primary p-2 text-primary-foreground transition-opacity disabled:opacity-40"
            aria-label="发送"
          >
            <Send className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
