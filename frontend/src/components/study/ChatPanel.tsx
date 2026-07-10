import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send } from 'lucide-react'

import Markdown from '@/components/study/Markdown'
import {
  listModels,
  streamChat,
  type ChatMessage,
  type DocumentInfo,
} from '@/lib/api'
import { useSettingsStore } from '@/stores/useSettingsStore'
import { useStudyStore } from '@/stores/useStudyStore'

interface ChatPanelProps {
  doc: DocumentInfo
}

/** 针对当前页的对话面板：模型选择 + 流式回答 + Markdown 渲染。 */
export default function ChatPanel({ doc }: ChatPanelProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const { selectedProfile, setSelectedProfile } = useSettingsStore()

  const { data: models = [] } = useQuery({ queryKey: ['models'], queryFn: listModels })

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 换页 = 换一段对话上下文，清空历史
  useEffect(() => {
    setMessages([])
    setError(null)
  }, [currentPage])

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
    if (!question || streaming || !selectedProfile) return

    const history: ChatMessage[] = [...messages, { role: 'user', content: question }]
    setMessages([...history, { role: 'assistant', content: '' }])
    setInput('')
    setStreaming(true)
    setError(null)

    try {
      for await (const ev of streamChat(doc.id, currentPage, selectedProfile, history)) {
        if (ev.type === 'delta') {
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = {
              role: 'assistant',
              content: next[next.length - 1].content + ev.text,
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
      </div>

      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">
            针对第 {currentPage} 页提问，或让模型出一道小测验。
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
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
          </div>
        ))}
        {error && <p className="text-sm text-destructive">出错了：{error}</p>}
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            rows={2}
            className="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <button
            onClick={() => void send()}
            disabled={streaming || !input.trim() || !selectedProfile}
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
