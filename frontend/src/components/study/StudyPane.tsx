import { ChevronLeft, ChevronRight } from 'lucide-react'

import ChatPanel from '@/components/study/ChatPanel'
import { type DocumentInfo } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

interface StudyPaneProps {
  doc: DocumentInfo
}

/** 右侧学习面板：页码导航 + 针对当前页的 LLM 对话。 */
export default function StudyPane({ doc }: StudyPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const goToPage = useStudyStore((s) => s.goToPage)

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
          第 {currentPage} / {doc.page_count} 页
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

      <div className="min-h-0 flex-1">
        <ChatPanel doc={doc} />
      </div>
    </div>
  )
}
