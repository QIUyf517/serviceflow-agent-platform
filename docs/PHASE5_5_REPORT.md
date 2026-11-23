# 阶段 5.5：商家知识库管理验收报告

日期：2026-11-23（Asia/Shanghai）

## 1. 范围与结论

本阶段只补齐商家维护静态知识的产品闭环，没有开始模型微调，也没有把订单实时物流、用户资料或支付数据写入向量库。商家可在管理后台建立 Markdown 草稿，发布通用快递、通常发货地、FAQ、商品说明和服务公告；顾客咨询能够检索发布内容并展示来源。

“通常发什么快递”属于静态商家说明；“某笔订单实际发了哪家快递、运单号和从哪个仓发出”仍属于履约实时事实，继续由已核验会话调用业务数据库。RAG 内容不参与身份、订单归属或取消/退货资格授权。

## 2. 数据与权限边界

新增 `merchant_knowledge_documents` 与 `merchant_knowledge_audit`。文档记录包含服务端绑定的 `merchant_id`、标题、分类、来源名称、版本、正文 SHA256、状态和生命周期时间；审计记录保存操作者、事件类型与不含正文的最小元数据。

API 使用现有独立 `X-Operator-Token`。请求模型没有 `merchant_id` 字段，商家身份来自 `MERCHANT_DEMO_ID`；跨商家读取返回未找到。当前 Token 是本地演示认证，不声称是生产 IAM。

状态流为：

```text
创建/编辑草稿 -> 显式发布 -> 顾客可检索 -> 归档 -> 从检索撤下
```

已发布内容不可直接更新。需要修改时归档旧版本并建立新草稿，避免无版本覆盖。重复创建同内容返回原文档，重复发布/归档为幂等结果。

## 3. 切分、向量与租户隔离

发布复用 `load_policy_text`：H2 为主要业务片段，H3 保留在父片段，元数据继续包含来源、版本、标题路径、稳定 chunk ID 和内容哈希。关键词路径使用现有中英文词项与中文字符序列/二元片段；这不是 jieba 语言学分词。向量路径使用 Embedding Provider 内部 tokenizer，无需应用层再次分词。

关键词和 pgvector 查询均接受允许来源前缀，在数据库查询阶段限制为固定全局政策/演示说明与当前商家 `merchant://<merchant_id>/knowledge/`。测试建立两个商家内容，商家 A 对商家 B 的唯一词查询为零命中；不是先全局召回后在展示层隐藏。

真实 PostgreSQL 验收环境：`pgvector 0.8.7`、FastEmbed `0.9.1`、`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`、384 维。随机 `phase6_knowledge_*` schema 发布 3 个片段，返回 `vector_status=indexed:3`，向量查询只返回当前商家来源；测试结束删除 schema。

默认 Compose 仍使用离线关键词检索。顾客聊天入口不再在代码里硬编码关键词，而是遵循 `POLICY_RETRIEVAL_STRATEGY`；配置 `auto`/`vector` 和可用 Provider 后可走 pgvector。向量失败不会伪装成向量成功。

## 4. API 示例

创建草稿：

```http
POST /api/v1/merchant/knowledge-documents
X-Operator-Token: <operator-token>
Content-Type: application/json

{
  "title": "店铺物流说明",
  "category": "logistics",
  "source_label": "商家物流规则",
  "version": "1.0.0",
  "content": "# 店铺物流说明\n\n## 默认快递\n\n普通订单通常使用中通或圆通。"
}
```

输出要点：`status=draft`、`chunk_count=0`。发布：

```http
POST /api/v1/merchant/knowledge-documents/<document-id>/publish
X-Operator-Token: <operator-token>
```

输出包含 `status=published`、真实 `chunk_count` 和 `vector_status`。检索预览为 `GET /api/v1/merchant/knowledge-documents/search?q=从哪里发货`；归档为 `POST /api/v1/merchant/knowledge-documents/<document-id>/archive`。

## 5. 前端

管理后台增加“人工工单 / 知识库”工作区切换。知识库采用来源台账与文档编辑纸面布局，支持新建、编辑草稿、发布、归档撤下和检索预览；状态分别显示草稿、已发布和已归档。移动端改为上下布局。界面明确提示具体订单物流仍由业务数据库提供。

## 6. 验收结果

| 命令/范围 | 结果 |
|---|---:|
| `pytest` 完整后端（设置真实 `TEST_DATABASE_URL`） | 273 passed，0 failed，0 skipped，140.03s |
| 新增商家知识专项（含真实 pgvector） | 4 passed |
| RAG/咨询相关回归 | 71 passed |
| `ruff check backend scripts tests` | 通过 |
| 前端 Vitest | 8 files，44 passed |
| ESLint / TypeScript / Vite build | 全部通过 |
| 外部 LLM 调用 | 0 |

Windows 受限沙箱中的 FastAPI TestClient 会在创建 asyncio 本地 socketpair 时阻塞；专项与全套 FastAPI 测试按既有项目做法在沙箱外执行。该现象属于测试运行权限，不是业务断言失败。

## 7. 已知边界

- 当前操作员 Token 和 `MERCHANT_DEMO_ID` 只适合单商家演示；生产环境需要组织、成员、角色和凭据轮换。
- 管理端当前接受文本/Markdown，不含 PDF、Word、网页抓取、OCR、病毒扫描或异步任务队列。
- 默认关键词路径在现有小知识集上更稳定；向量模式需要可用 pgvector 和 Embedding Provider。
- 商家内容是咨询证据，不是取消、退货、支付或订单变更授权。
