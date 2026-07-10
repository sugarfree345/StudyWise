import { documentFileUrl, type DocumentInfo } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

interface PdfPaneProps {
  doc: DocumentInfo
}

/**
 * PDF 展示窗格。
 * 最小实现：浏览器原生查看器（iframe + #page=N）。
 * 之后可换成 pdf.js / react-pdf，实现滚动监听等更精确的页码双向同步。
 */
export default function PdfPane({ doc }: PdfPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)

  return (
    <iframe
      key={currentPage}
      src={`${documentFileUrl(doc.id)}#page=${currentPage}`}
      title={doc.filename}
      className="h-full w-full"
    />
  )
}
