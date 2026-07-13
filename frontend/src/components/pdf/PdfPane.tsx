import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'
import './PdfPane.css'

import { documentFileUrl, type DocumentInfo } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface PdfPaneProps {
  doc: DocumentInfo
  resizingLayout?: boolean
}

interface ResizeAnchor {
  page: number
  progress: number
}

/**
 * 使用 React-PDF 连续渲染整本 PDF，支持上下滚动翻页。
 * 滚动时用 IntersectionObserver 推断“当前页”，同步到全局状态；
 * 右侧的上一页/下一页按钮改变 currentPage 时，则把对应页滚动到视口。
 */
export default function PdfPane({ doc, resizingLayout = false }: PdfPaneProps) {
  const currentPage = useStudyStore((s) => s.currentPage)
  const goToPage = useStudyStore((s) => s.goToPage)
  const containerRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])
  const [pageWidth, setPageWidth] = useState<number>()
  const [numPages, setNumPages] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // 记录滚动推断出的可见页，用来区分“按钮翻页”和“滚动翻页”，避免相互抖动。
  const visiblePageRef = useRef(currentPage)
  const resizingRef = useRef(false)
  const resizeAnchorRef = useRef<ResizeAnchor | null>(null)
  const restoreFrameRef = useRef<number | null>(null)

  const captureResizeAnchor = useCallback(() => {
    const container = containerRef.current
    const page = visiblePageRef.current
    const element = pageRefs.current[page - 1]
    if (!container || !element) return
    const containerRect = container.getBoundingClientRect()
    const pageRect = element.getBoundingClientRect()
    const progress = Math.min(
      1,
      Math.max(0, (containerRect.top - pageRect.top) / Math.max(1, pageRect.height)),
    )
    resizeAnchorRef.current = { page, progress }
  }, [])

  const restoreResizeAnchor = useCallback(() => {
    const container = containerRef.current
    const anchor = resizeAnchorRef.current
    const element = anchor ? pageRefs.current[anchor.page - 1] : null
    if (!container || !anchor || !element) return
    const containerRect = container.getBoundingClientRect()
    const pageRect = element.getBoundingClientRect()
    const currentTop = pageRect.top - containerRect.top
    const desiredTop = -anchor.progress * pageRect.height
    container.scrollTop += currentTop - desiredTop
  }, [])

  useLayoutEffect(() => {
    if (resizingLayout) {
      resizingRef.current = true
      captureResizeAnchor()
      return
    }
    if (!resizingRef.current) return

    // 等最终宽度和 PDF 页面尺寸都提交后再解锁页码观察器。
    restoreFrameRef.current = window.requestAnimationFrame(() => {
      restoreFrameRef.current = window.requestAnimationFrame(() => {
        restoreFrameRef.current = null
        restoreResizeAnchor()
        const anchor = resizeAnchorRef.current
        if (anchor) {
          visiblePageRef.current = anchor.page
          goToPage(anchor.page)
        }
        resizingRef.current = false
        resizeAnchorRef.current = null
      })
    })
    return () => {
      if (restoreFrameRef.current !== null) {
        window.cancelAnimationFrame(restoreFrameRef.current)
        restoreFrameRef.current = null
      }
    }
  }, [resizingLayout, captureResizeAnchor, restoreResizeAnchor, goToPage])

  useLayoutEffect(() => {
    if (!resizingRef.current) return
    const frame = window.requestAnimationFrame(restoreResizeAnchor)
    return () => window.cancelAnimationFrame(frame)
  }, [pageWidth, restoreResizeAnchor])

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

  // 监听各页可见比例，取最靠上、可见度最高的一页作为当前页。
  useEffect(() => {
    const container = containerRef.current
    if (!container || numPages === 0 || resizingLayout) return

    const ratios = new Map<number, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        if (resizingRef.current) return
        for (const entry of entries) {
          const page = Number((entry.target as HTMLElement).dataset.page)
          ratios.set(page, entry.isIntersecting ? entry.intersectionRatio : 0)
        }
        let best = visiblePageRef.current
        let bestRatio = 0
        for (const [page, ratio] of ratios) {
          if (ratio > bestRatio) {
            best = page
            bestRatio = ratio
          }
        }
        if (bestRatio > 0 && best !== visiblePageRef.current) {
          visiblePageRef.current = best
          goToPage(best)
        }
      },
      { root: container, threshold: [0.1, 0.25, 0.5, 0.75, 1] },
    )

    for (const el of pageRefs.current) {
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [numPages, goToPage, resizingLayout])

  // 外部（按钮/页码输入）改变 currentPage 时，把该页滚动到视口顶部。
  useEffect(() => {
    if (currentPage === visiblePageRef.current) return
    const el = pageRefs.current[currentPage - 1]
    if (el) {
      visiblePageRef.current = currentPage
      el.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }
  }, [currentPage])

  return (
    <div ref={containerRef} className="h-full overflow-auto bg-muted/40 p-4">
      {error ? (
        <p className="text-sm text-destructive">PDF 加载失败：{error}</p>
      ) : (
        <Document
          file={documentFileUrl(doc.id)}
          loading={<p className="text-sm text-muted-foreground">正在加载 PDF…</p>}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          onLoadError={(cause) => setError(cause.message)}
          className="flex flex-col items-center gap-4"
        >
          {pageWidth &&
            Array.from({ length: numPages }, (_, index) => (
              <div
                key={index}
                data-page={index + 1}
                ref={(el) => {
                  pageRefs.current[index] = el
                }}
              >
                <Page
                  pageNumber={index + 1}
                  width={pageWidth}
                  loading={
                    <p className="text-sm text-muted-foreground">
                      正在渲染第 {index + 1} 页…
                    </p>
                  }
                  renderAnnotationLayer
                  renderTextLayer
                  onRenderSuccess={() => {
                    if (
                      resizingRef.current &&
                      resizeAnchorRef.current?.page === index + 1
                    ) {
                      restoreResizeAnchor()
                    }
                  }}
                  className="overflow-hidden shadow-lg"
                />
              </div>
            ))}
        </Document>
      )}
    </div>
  )
}
