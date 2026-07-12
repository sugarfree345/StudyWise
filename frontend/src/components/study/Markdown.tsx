import { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

/**
 * 大模型常输出 TeX 原生分隔符 \(...\) / \[...\]；remark-math 使用的是
 * $...$ / $$...$$。必须在 Markdown 解析前转换，否则反斜杠会被当作转义字符吃掉。
 */
function normalizeMathDelimiters(markdown: string): string {
  return markdown
    // 用回调避免 String.replace 把 $$ 解释为替换语法而缩成单个 $。
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, math: string) => `\n\n$$\n${math}\n$$\n\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, math: string) => `$${math}$`)
}

/** 大模型回答的 Markdown 渲染：表格、代码高亮，以及 KaTeX 数学公式。 */
function Markdown({ children }: { children: string }) {
  const normalized = useMemo(() => normalizeMathDelimiters(children), [children])
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert prose-pre:bg-muted prose-pre:text-foreground">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeHighlight, rehypeKatex]}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  )
}

export default memo(Markdown)
