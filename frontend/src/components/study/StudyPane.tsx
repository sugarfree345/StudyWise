import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { getPageText, type DocumentInfo } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

interface StudyPaneProps {
  doc: DocumentInfo
}

/** 右侧学习面板：页码导航 + 本页内容预览 + 提问/测验（待接入 LLM）。 */
export default function StudyPane({ doc }: StudyPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const goToPage = useStudyStore((s) => s.goToPage)

  const { data: page, isFetching } = useQuery({
    queryKey: ['page-text', doc.id, currentPage],
    queryFn: () => getPageText(doc.id, currentPage),
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

      <div className="flex-1 space-y-6 overflow-y-auto p-4">
        <section>
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
            本页文字{isFetching && '（加载中…）'}
          </h2>
          <pre className="whitespace-pre-wrap rounded-lg bg-muted p-3 font-sans text-xs leading-relaxed">
            {page?.text.trim() || '（本页没有可提取的文字）'}
          </pre>
        </section>

        <section>
          <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
            对本页提问 / 生成小测验
          </h2>
          <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            LLM 对话与测验功能待接入
          </div>
        </section>
      </div>
    </div>
  )
}
