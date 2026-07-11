import { useEffect, useRef, useState, type ReactNode } from 'react'

interface SplitViewProps {
  left: ReactNode
  right: ReactNode
}

/** 左右对照布局：左侧资料原文，右侧学习面板，页码保持同步。 */
export default function SplitView({ left, right }: SplitViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftWidth, setLeftWidth] = useState(() => {
    const saved = Number(window.localStorage.getItem('studywise-split-left-width'))
    return Number.isFinite(saved) && saved >= 25 && saved <= 75 ? saved : 50
  })
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    if (!dragging) return
    const move = (event: PointerEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const next = Math.min(75, Math.max(25, ((event.clientX - rect.left) / rect.width) * 100))
      setLeftWidth(next)
    }
    const stop = () => setDragging(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
  }, [dragging])

  useEffect(() => {
    window.localStorage.setItem('studywise-split-left-width', String(leftWidth))
  }, [leftWidth])

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1">
      <section className="min-h-0 shrink-0" style={{ width: `${leftWidth}%` }}>{left}</section>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="调整 PDF 与对话面板宽度"
        onPointerDown={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        className={`group relative w-1 shrink-0 cursor-col-resize bg-border transition-colors hover:bg-primary ${dragging ? 'bg-primary' : ''}`}
      >
        <span className="absolute inset-y-0 -left-1 -right-1" />
      </div>
      <section className="min-h-0 min-w-0 flex-1">{right}</section>
    </div>
  )
}
