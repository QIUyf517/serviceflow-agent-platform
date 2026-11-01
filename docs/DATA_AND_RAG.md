# τ-bench Retail 数据导入与知识库方案

## 1. 官方来源与路径

- 仓库：https://github.com/sierra-research/tau2-bench
- 当前仓库数据目录：`data/tau2/domains/retail/`
- 关注文件：`db.json`、`policy.md`、`tasks.json`、`split_tasks.json`（实际以所固定版本文件为准）。
- 参考代码：`src/tau2/domains/retail/data_model.py`、`tools.py`、`environment.py`。
- 旧版仓库/ Hugging Face 镜像有不同目录布局，不要在脚本中混用；所有导入步骤以单个明确的官方 Git commit 为准。

下载建议：

```bash
git clone https://github.com/sierra-research/tau2-bench.git vendor/tau2-bench
cd vendor/tau2-bench
git rev-parse HEAD        # 记录实际commit，后续固定这一版本
cd ../..
```

`vendor/tau2-bench` 仅在本地使用，放入 `.gitignore`；**不要直接提交其完整源码或隐式跟随main更新**。可以在第一轮勘察后确定稳定的 tag/commit 并锁定。

## 2. 数据分流

| 数据 | 去向 | 用途 | 不该做的事 |
|---|---|---|---|
| `db.json` | PostgreSQL结构化业务表 | 用户、商品、订单、变体、支付/配送等模拟状态 | 不要把所有客户订单灌进RAG检索 |
| `policy.md` | 文档分段、政策引用（初期直接读Markdown） | 规则查询和解释 | 不要用向量相似度决定是否允许退款/取消 |
| `tasks.json` | 受控测试目录（非运行时业务库） | 客服任务测试和构造开发集 | 不要向Agent暴露评测目标与参考工具动作 |
| `split_tasks.json` | 评测配置 | 隔离训练与保留测试 | 不要把保留测试用作训练或调Prompt |
| `data_model.py`, `tools.py` | 作为设计参考 | API字段、工具参数、业务约束 | 不直接把上游工具当成不受控线上服务 |

## 3. 结构化数据导入规范

第一步用 Python 读取 JSON 顶层键及样本结构，核实字段。历史 Retail 数据常见集合为 `users`、`products`、`orders`，实际结构以下载的源文件为准。推荐初期建立这些表：

- `users`：source_user_id、display_name、email、profile_json、updated_at。
- `products`：source_product_id、name、product_json；`product_variants`：source_item_id、source_product_id、option_json、price、availability。
- `orders`：source_order_id、source_user_id、status、order_json、row_version、updated_at。
- `order_items`：source_order_id、source_item_id、quantity、price_snapshot、item_json。
- `tickets`、`conversations`、`messages`：项目新增的客服业务数据。
- `operation_requests`：proposal_id、operation_id/idempotency_key、action_type、status、payload、confirmed_at、result。
- `audit_events`：不可覆盖的审计事件。
- `policy_documents`/`knowledge_chunks`：政策文本、来源版本、段落/向量引用。

**重要：** 这些是我们自己的表设计，不意味着 `db.json` 内每个字段都能原样对应。导入时为原始嵌套结构保留JSONB，渐进规范化并验证关系约束。禁止生成真实支付凭据或宣称模拟订单代表真实客户。

## 4. RAG的真正用途

初期 `policy.md` 较短，先做 **section-based retrieval**：按 Markdown 标题划分，检索相关章节，返回引用路径+小节标题。与LLM交互前先规则检索，再用代码检查可执行性。

在产品扩展阶段，新增并注明为**自建模拟文档**的FAQ、售后指南、产品手册、物流说明和政策历史版本，才有必要引入 Embedding + pgvector：

1. 文档解析与 chunking（保留标题、来源、更新时间、policy_version）。
2. Embedding写入 PostgreSQL pgvector；可加关键词/BM25混合检索。
3. 检索 top-k + 规则/权限过滤；返回引用和检索置信度。
4. 若证据不足，让客服说明不确定或转人工，禁止编造规则。
5. 用标注问题集合测 `Recall@k`、引用准确率、无依据回答率。

**RAG不负责：** 实时订单状态、用户身份授权、退款/订单资格判定、付款动作。

## 5. 微调数据的严格边界

`tasks.json` 是测试任务而不是天然对话SFT数据；可能包含正确结果、参考动作等，会泄露答案。

- 先做 API + Multi-Agent + RAG，不把微调纳入MVP关键路径。
- 需要SFT时，只用许可允许的训练子集及明确可用的成功交互轨迹；转换为 messages/tool_calls/observations 格式，清除评测标签与不必要的用户标识。
- 保留未接触的验证/测试集；记录样本生成方式、模型版本、许可和训练数据谱系。
- 不能训练后仍在相同曝光任务集上宣称为纯零样本泛化。

## 6. 版本与许可

在 `data/manifest.json` 记录：仓库URL、commit SHA、获取日期、每个文件SHA256、许可证、数据用途和导入数量。检查原仓库与数据集许可证文件并按其要求署名；不要凭文件路径推断许可。数据原文件不纳入公共Git仓库，除非确认适合再分发。
