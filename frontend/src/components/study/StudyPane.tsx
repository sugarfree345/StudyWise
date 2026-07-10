import { useMutation } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import ChatPanel from '@/components/study/ChatPanel'
import { reparseDocument, type DocumentInfo } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'
import { useStudyStore } from '@/stores/useStudyStore'

interface StudyPaneProps {
  doc: DocumentInfo
}

/** 右侧学习面板：页码导航 + 针对当前页的 LLM 对话。 */
export default function StudyPane({ doc }: StudyPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const goToPage = useStudyStore((s) => s.goToPage)
  const reparse = useMutation({
    mutationFn: () => reparseDocument(doc.id),
    onSuccess: (updated) => {
      queryClient.setQueryData(['documents', doc.id], updated)
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-center gap-4 border-b border-border py-2">
        <button
          onClick={() => goToPage(currentPage - 1)}
          disabled={currentPage <= 1}
          className="rounded p-1 transition-colors hover:bg-accent disabled:opacity-40"
          aria-label="上一页"
        >
          <ChevronLeft className="size-5" />
        </button>
        <span className="text-sm tabular-nums">
          {doc.page_count > 0
            ? `第 ${currentPage} / ${doc.page_count} 页`
            : '页数识别中'}
        </span>
        <button
          onClick={() => goToPage(currentPage + 1)}
          disabled={currentPage >= doc.page_count}
          className="rounded p-1 transition-colors hover:bg-accent disabled:opacity-40"
          aria-label="下一页"
        >
          <ChevronRight className="size-5" />
        </button>
      </div>

      {doc.parse_status !== 'ready' && (
        <div
          className={
            doc.parse_status === 'failed'
              ? 'border-b border-border bg-destructive/10 px-3 py-2 text-sm text-destructive'
              : 'border-b border-border bg-accent px-3 py-2 text-sm text-muted-foreground'
          }
        >
          {doc.parse_status === 'pending' && '文档正在等待 OCR 解析…'}
          {doc.parse_status === 'processing' &&
            `PaddleOCR 正在解析：${doc.processed_pages} / ${doc.page_count} 页`}
          {doc.parse_status === 'failed' && (
            <span className="flex items-center justify-between gap-2">
              <span className="truncate">解析失败：{doc.parse_error ?? '未知错误'}</span>
              <button
                type="button"
                onClick={() => reparse.mutate()}
                disabled={reparse.isPending}
                className="shrink-0 rounded border border-destructive px-2 py-1"
              >
                {reparse.isPending ? '重试中…' : '重新解析'}
              </button>
            </span>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1">
        <ChatPanel doc={doc} />
      </div>
    </div>
  )
}
