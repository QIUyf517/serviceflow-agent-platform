import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import type {
  KnowledgeCategory,
  KnowledgeDocument,
  KnowledgeDocumentInput,
  KnowledgeSearchHit,
} from '../../api/adminTypes'
import { ApiError } from '../../api/errors'
import { operatorApi } from '../../api/operator'

const TEMPLATE = `# 店铺物流说明

## 默认快递

普通订单通常使用中通或圆通。具体承运商以订单发货后的物流记录为准。

## 发货地点

普通商品一般从杭州仓发出，但会根据库存和收货区域调度仓库。
具体订单的实际发货仓以订单履约信息为准。
`

const EMPTY: KnowledgeDocumentInput = {
  title: '店铺物流说明',
  category: 'logistics',
  source_label: '商家物流规则',
  version: '1.0.0',
  content: TEMPLATE,
}

const CATEGORY_LABELS: Record<KnowledgeCategory, string> = {
  logistics: '物流与发货',
  faq: '常见问题',
  product_guide: '商品说明',
  service_notice: '服务公告',
}

const STATUS_LABELS: Record<KnowledgeDocument['status'], string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

function message(error: unknown): string {
  if (error instanceof ApiError) return `知识库操作未完成：${error.code}`
  return '知识库操作未完成，请检查后端连接。'
}

export function KnowledgeWorkspace() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<KnowledgeDocumentInput>(EMPTY)
  const [editingId, setEditingId] = useState<string>()
  const [previewQuery, setPreviewQuery] = useState('发什么快递，从哪里发货')
  const [previewHits, setPreviewHits] = useState<KnowledgeSearchHit[]>([])
  const [actionError, setActionError] = useState<string>()

  const documents = useQuery({
    queryKey: ['operator', 'knowledge'],
    queryFn: operatorApi.listKnowledge,
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['operator', 'knowledge'] })
  const save = useMutation({
    mutationFn: () => editingId
      ? operatorApi.updateKnowledge(editingId, form)
      : operatorApi.createKnowledge(form),
    onMutate: () => setActionError(undefined),
    onSuccess: (document) => {
      setEditingId(document.id)
      void refresh()
    },
    onError: (error) => setActionError(message(error)),
  })
  const publish = useMutation({
    mutationFn: operatorApi.publishKnowledge,
    onMutate: () => setActionError(undefined),
    onSuccess: () => {
      setEditingId(undefined)
      setForm(EMPTY)
      void refresh()
    },
    onError: (error) => setActionError(message(error)),
  })
  const archive = useMutation({
    mutationFn: operatorApi.archiveKnowledge,
    onMutate: () => setActionError(undefined),
    onSuccess: () => {
      setEditingId(undefined)
      void refresh()
    },
    onError: (error) => setActionError(message(error)),
  })
  const preview = useMutation({
    mutationFn: operatorApi.searchKnowledge,
    onMutate: () => setActionError(undefined),
    onSuccess: (result) => setPreviewHits(result.hits),
    onError: (error) => setActionError(message(error)),
  })

  function selectDraft(document: KnowledgeDocument) {
    if (document.status !== 'draft') return
    setEditingId(document.id)
    setForm({
      title: document.title,
      category: document.category,
      source_label: document.source_label,
      version: document.version,
      content: document.content,
    })
    setActionError(undefined)
  }

  function newDraft() {
    setEditingId(undefined)
    setForm(EMPTY)
    setActionError(undefined)
  }

  const pending = save.isPending || publish.isPending || archive.isPending || preview.isPending

  return (
    <section className="knowledge-workspace" aria-label="商家知识库">
      <aside className="knowledge-ledger">
        <header>
          <div>
            <h2>知识来源</h2>
            <p>{documents.data?.merchant_id ?? '当前商家'} · 发布后顾客才可检索</p>
          </div>
          <button className="text-button" type="button" onClick={newDraft}>新建草稿</button>
        </header>
        {documents.isLoading ? <p>正在读取知识来源…</p> : null}
        {documents.error ? <p role="alert">{message(documents.error)}</p> : null}
        <ol className="knowledge-list">
          {documents.data?.items.map((document) => (
            <li key={document.id} className={editingId === document.id ? 'is-selected' : undefined}>
              <div>
                <strong>{document.title}</strong>
                <span className={`knowledge-status is-${document.status}`}>
                  {STATUS_LABELS[document.status]}
                </span>
              </div>
              <p>{CATEGORY_LABELS[document.category]} · v{document.version} · {document.chunk_count} 个片段</p>
              <div className="knowledge-row-actions">
                {document.status === 'draft' ? (
                  <>
                    <button type="button" onClick={() => selectDraft(document)}>编辑</button>
                    <button type="button" disabled={pending} onClick={() => publish.mutate(document.id)}>
                      发布
                    </button>
                  </>
                ) : null}
                {document.status === 'published' ? (
                  <button type="button" disabled={pending} onClick={() => archive.mutate(document.id)}>
                    归档并撤下
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
        {!documents.isLoading && documents.data?.items.length === 0 ? (
          <p className="knowledge-empty">还没有商家知识。先建立一份物流或常见问题草稿。</p>
        ) : null}
      </aside>

      <div className="knowledge-editor">
        <header>
          <div>
            <h2>{editingId ? '编辑草稿' : '建立知识来源'}</h2>
            <p>用二级标题分隔主题。订单的实际快递与发货仓仍从业务数据库读取。</p>
          </div>
          <span>Markdown</span>
        </header>
        <form onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
          <div className="knowledge-fields">
            <label>
              标题
              <input value={form.title} maxLength={160} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </label>
            <label>
              分类
              <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as KnowledgeCategory })}>
                {Object.entries(CATEGORY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>
              来源名称
              <input value={form.source_label} maxLength={200} onChange={(event) => setForm({ ...form, source_label: event.target.value })} />
            </label>
            <label>
              版本
              <input value={form.version} maxLength={64} pattern="[A-Za-z0-9._-]+" onChange={(event) => setForm({ ...form, version: event.target.value })} />
            </label>
          </div>
          <label className="knowledge-content">
            知识正文
            <textarea value={form.content} maxLength={100000} onChange={(event) => setForm({ ...form, content: event.target.value })} />
          </label>
          {actionError ? <p role="alert">{actionError}</p> : null}
          <div className="knowledge-editor-actions">
            <button className="button" type="submit" disabled={pending}>保存草稿</button>
            <span>已发布内容不可直接覆盖；请归档后建立新版本。</span>
          </div>
        </form>

        <section className="knowledge-preview" aria-label="检索预览">
          <header>
            <div>
              <h3>检索预览</h3>
              <p>只检查已发布的当前商家知识，不读取客户订单。</p>
            </div>
          </header>
          <form onSubmit={(event) => { event.preventDefault(); preview.mutate(previewQuery) }}>
            <input aria-label="测试问题" value={previewQuery} onChange={(event) => setPreviewQuery(event.target.value)} />
            <button type="submit" disabled={pending}>测试检索</button>
          </form>
          <ol>
            {previewHits.map((hit) => (
              <li key={hit.chunk_id}>
                <strong>{hit.section}</strong>
                <span>相关分 {hit.score.toFixed(3)}</span>
                <p>{hit.content.slice(0, 260)}</p>
              </li>
            ))}
          </ol>
          {preview.isSuccess && previewHits.length === 0 ? <p>没有命中。检查文档是否已发布，或补充相关表述。</p> : null}
        </section>
      </div>
    </section>
  )
}
