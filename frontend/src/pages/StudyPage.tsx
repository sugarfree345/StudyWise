import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router'

import SplitView from '@/components/layout/SplitView'
import PdfPane from '@/components/pdf/PdfPane'
import StudyPane from '@/components/study/StudyPane'
import { getDocument } from '@/lib/api'
import { useStudyStore } from '@/stores/useStudyStore'

export default function StudyPage() {
  const { documentId } = useParams()
  const id = Number(documentId)
  const setPageCount = useStudyStore((s) => s.setPageCount)

  const {
    data: doc,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['documents', id],
    queryFn: () => getDocument(id),
    enabled: Number.isFinite(id),
    refetchInterval: (query) => {
      const status = query.state.data?.parse_status
      return status === 'pending' || status === 'processing' ? 1500 : false
    },
  })
  const documentPageCount = doc?.page_count

  useEffect(() => {
    if (documentPageCount && documentPageCount > 0) {
      setPageCount(documentPageCount)
    }
  }, [documentPageCount, setPageCount])

  if (isLoading) {
    return <p className="p-6 text-muted-foreground">加载中…</p>
  }
  if (isError || !doc) {
    return <p className="p-6 text-destructive">文档加载失败。</p>
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-border px-4 py-2">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-5" />
        </Link>
        <h1 className="truncate text-sm font-medium">{doc.filename}</h1>
      </header>
      <SplitView left={<PdfPane doc={doc} />} right={<StudyPane doc={doc} />} />
    </div>
  )
}
