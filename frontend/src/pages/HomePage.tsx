import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { FileText, FileUp } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import {
  createProject,
  listProjectDocuments,
  listProjects,
  uploadProjectDocument,
} from '@/lib/api'
import { queryClient } from '@/lib/queryClient'

function processingLabel(
  status: 'pending' | 'processing' | 'ready' | 'failed',
  processedPages: number,
  pageCount: number,
) {
  if (status === 'pending') return '等待解析'
  if (status === 'processing') return `解析中 ${processedPages}/${pageCount}`
  if (status === 'failed') return '解析失败'
  return '解析完成'
}

export default function HomePage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [newProjectName, setNewProjectName] = useState('')

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  })
  const { data: documents = [], isLoading } = useQuery({
    queryKey: ['projects', selectedProjectId, 'documents'],
    queryFn: () => listProjectDocuments(selectedProjectId!),
    enabled: selectedProjectId !== null,
    refetchInterval: (query) =>
      query.state.data?.some((doc) =>
        ['pending', 'processing'].includes(doc.parse_status),
      )
        ? 1500
        : false,
  })

  useEffect(() => {
    if (
      projects.length > 0 &&
      !projects.some((project) => project.id === selectedProjectId)
    ) {
      setSelectedProjectId(projects[0].id)
    }
  }, [projects, selectedProjectId])

  const upload = useMutation({
    mutationFn: ({ projectId, file }: { projectId: number; file: File }) =>
      uploadProjectDocument(projectId, file),
    onSuccess: (doc) => {
      void queryClient.invalidateQueries({
        queryKey: ['projects', doc.project_id, 'documents'],
      })
      navigate(`/study/${doc.id}`)
    },
  })
  const create = useMutation({
    mutationFn: (name: string) => createProject(name),
    onSuccess: (project) => {
      setNewProjectName('')
      setSelectedProjectId(project.id)
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
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

      <div className="space-y-3">
        <div className="flex gap-2">
          <select
            value={selectedProjectId ?? ''}
            onChange={(event) => setSelectedProjectId(Number(event.target.value))}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-2"
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <input
            value={newProjectName}
            onChange={(event) => setNewProjectName(event.target.value)}
            placeholder="新项目名称"
            className="min-w-0 flex-1 rounded-md border border-border px-3 py-2"
          />
          <button
            type="button"
            disabled={!newProjectName.trim() || create.isPending}
            onClick={() => create.mutate(newProjectName.trim())}
            className="rounded-md border border-border px-3 py-2 disabled:opacity-40"
          >
            新建
          </button>
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={upload.isPending || selectedProjectId === null}
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
            if (file && selectedProjectId !== null) {
              upload.mutate({ projectId: selectedProjectId, file })
            }
            event.target.value = ''
          }}
        />
        {upload.isError && (
          <p className="mt-2 text-sm text-destructive">{upload.error.message}</p>
        )}
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">项目资料</h2>
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
            <span className="min-w-0 flex-1">
              <span className="block truncate">{doc.filename}</span>
              <span
                className={
                  doc.parse_status === 'failed'
                    ? 'text-xs text-destructive'
                    : 'text-xs text-muted-foreground'
                }
              >
                {processingLabel(doc.parse_status, doc.processed_pages, doc.page_count)}
              </span>
            </span>
            <span className="text-sm text-muted-foreground">{doc.page_count} 页</span>
          </Link>
        ))}
      </section>
    </main>
  )
}
