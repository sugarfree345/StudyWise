import { useEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

import { documentFileUrl, type DocumentInfo } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface PdfPaneProps {
  doc: DocumentInfo
}

/** 使用 React-PDF 渲染当前页，并保留文字层和注释层供后续元素交互使用。 */
export default function PdfPane({ doc }: PdfPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const containerRef = useRef<HTMLDivElement>(null)
  const [pageWidth, setPageWidth] = useState<number>()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const updateWidth = (width: number) => {
      setPageWidth(Math.max(240, Math.floor(width - 32)))
    }
    updateWidth(container.clientWidth)

    const observer = new ResizeObserver(([entry]) => {
      updateWidth(entry.contentRect.width)
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={containerRef}
      className="flex h-full justify-center overflow-auto bg-muted/40 p-4"
    >
      {error ? (
        <p className="self-start text-sm text-destructive">PDF 加载失败：{error}</p>
      ) : (
        <Document
          file={documentFileUrl(doc.id)}
          loading={<p className="text-sm text-muted-foreground">正在加载 PDF…</p>}
          onLoadError={(cause) => setError(cause.message)}
        >
          {pageWidth && (
            <Page
              pageNumber={currentPage}
              width={pageWidth}
              loading={<p className="text-sm text-muted-foreground">正在渲染第 {currentPage} 页…</p>}
              renderAnnotationLayer
              renderTextLayer
              className="overflow-hidden shadow-lg"
            />
          )}
        </Document>
      )}
    </div>
  )
}
