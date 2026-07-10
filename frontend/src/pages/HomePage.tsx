import { useRef } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, FileUp } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { listDocuments, uploadDocument } from '@/lib/api'
import { queryClient } from '@/lib/queryClient'

export default function HomePage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: listDocuments,
  })

  const upload = useMutation({
    mutationFn: uploadDocument,
    onSuccess: (doc) => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      navigate(`/study/${doc.id}`)
    },
  })

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 px-6 py-16">
      <header>
        <h1 className="text-3xl font-bold">StudyWise</h1>
        <p className="mt-2 text-muted-foreground">
          上传 PDF 课件或论文，逐页向大模型提问、生成小测验。
        </p>
      </header>

      <div>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={upload.isPending}
          className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border p-10 text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
        >
          <FileUp className="size-5" />
          {upload.isPending ? '上传中…' : '点击选择 PDF 上传'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) upload.mutate(file)
            event.target.value = ''
          }}
        />
        {upload.isError && (
          <p className="mt-2 text-sm text-destructive">{upload.error.message}</p>
        )}
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">我的资料</h2>
        {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
        {!isLoading && documents.length === 0 && (
          <p className="text-sm text-muted-foreground">
            还没有上传任何资料（需要后端已启动）。
          </p>
        )}
        {documents.map((doc) => (
          <Link
            key={doc.id}
            to={`/study/${doc.id}`}
            className="flex items-center gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-accent"
          >
            <FileText className="size-5 shrink-0 text-muted-foreground" />
            <span className="flex-1 truncate">{doc.filename}</span>
            <span className="text-sm text-muted-foreground">{doc.page_count} 页</span>
          </Link>
        ))}
      </section>
    </main>
  )
}
