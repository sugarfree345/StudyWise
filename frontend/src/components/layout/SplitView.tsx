import type { ReactNode } from 'react'

interface SplitViewProps {
  left: ReactNode
  right: ReactNode
}

/** 左右对照布局：左侧资料原文，右侧学习面板，页码保持同步。 */
export default function SplitView({ left, right }: SplitViewProps) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-2">
      <section className="min-h-0 border-r border-border">{left}</section>
      <section className="min-h-0">{right}</section>
    </div>
  )
}
