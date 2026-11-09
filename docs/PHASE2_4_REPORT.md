# 阶段 2.4：Policy Agent + RAG 政策检索验收报告

日期：2026-11-02（Asia/Shanghai）。本阶段只实现政策知识库、关键词/pgvector 检索接口、Policy Agent 及其与现有 Triage、Supervisor、Order Agent、`AgentState` 的只读集成。未实现 Resolution Agent、写操作工作流、人工审批或前端，也没有进入 2.5。

## 事实核验与知识库

项目实际包名为 `serviceflow`，根目录就是当前工作区。政策源为阶段 0 下载的 `data/raw/tau2/da0835f6c67baef58bdda18f2a3b037dfb3a1754/policy.md`：

- 上游 commit：`da0835f6c67baef58bdda18f2a3b037dfb3a1754`。
- 文件大小：6,699 bytes。
- SHA256：`2c9652afbce57d6e087768d37cda64d31c53d50b3e3225cfdb791bac66466467`。
- 实际结构：1 个 H1，6 个 H2，5 个 H3。导入后为 1 份文档、7 个 chunk。

切分以 H2 业务条款为主：顶层通用政策为独立 chunk；`Domain basic`、`Generic action rules`、取消、修改、退货、换货各为一个 chunk。`Modify payment` 和 `Modify items` 等 H3 子节保留在父 chunk 内，避免资格条件、例外与后果分离。元数据包含标题路径、相对源路径、commit、文档/片段 SHA256、序号和稳定 `chunk_id`。官方原文未修改。

`policy_documents` / `policy_chunks` 使用文档版本和序号唯一约束。真实 PostgreSQL 首次导入实测为 `inserted=7`，第二次为 `inserted=0, unchanged=true`；库内实际为 1 份文档、7 个 chunk。同版本源哈希变更时默认拒绝，只有显式 `--rebuild` 才替换该文档的 chunk。

## 两套检索实现与实测

关键词 Baseline 在库内的完整 section chunk 上执行中英文词项、标题加权和有限业务同义词匹配。它返回 Top-K、确定性相关分数、完整原文、章节、源文件、commit 和 chunk ID。该分数只用于同一查询内排序，不是统计校准后的概率。空命中不生成政策。

向量方案已实现 OpenAI-compatible `/embeddings` 批量调用、模型/维度校验、`vector(n)` 建表、幂等 upsert、cosine distance Top-K 及显式重建。密钥仅从 `POLICY_EMBEDDING_API_KEY` 读取，不在代码中。当选择 `vector` 而 Provider/扩展不可用时返回错误；只有 `auto` 模式可显式返回 `keyword_fallback`，并同时记录向量失败代码。

当前环境的真实状态是：PostgreSQL 16.15 的 `pg_available_extensions` 中无 `vector`，`pg_extension` 中也未安装；`.env` 未配置 Embedding 专用 Key。因此未生成任何向量，不报告伪造向量成绩。

30 条自建标注集覆盖取消、修改、退货、换货、通用规则、身份/确认和中文多表达。指标是本机单次真实运行，不是模型总体准确率：

| 方法 | 样本量 | Recall@3 | MRR | 平均检索延迟 |
|---|---:|---:|---:|---:|
| 关键词 | 30 | 1.000000 | 0.961111 | 0.961 ms |
| pgvector 向量 | 30 | N/A | N/A | N/A（扩展与 Key 不可用） |

逐条结果在 `reports/phase2_4_retrieval.json`。引用准确性测试校验：回答中每个 citation ID 都必须来自本轮真实 Top-K；30 条中正确标注章节全部在 Top-3 中。这不等于已证明任意问题的回答正确。

## Policy Agent 与共享状态

新路径是 `START → Triage → Supervisor → Policy → Supervisor result → terminal → END`。复合请求可先运行 Order，再运行 Policy；Policy 完成后只将对应子任务标记为 `completed`，Guard、Resolution、Confirmation 和 Executor 仍为 `pending/blocked`。图不会将它们当成已执行，也不会回跳重复查询。

Policy Agent 更新：

- `policy_context`：最小可溯源证据（来源、章节、版本、excerpt、chunk ID、分数、方法）。
- `policy_retrieval`：调试所需的查询、Top-K、耗时和完整命中。
- `tool_results`：检索成功/错误代码，包括显式 vector fallback。
- `trace`：节点、方法、查询、Top-K 和结果状态。
- `final_response`：证据限定说明、服务端生成的 verified citations 和非授权边界。

具体订单问题会明确说明还需身份、实时状态、商品/付款参数与服务端硬规则验证。Policy Agent 没有订单库或写工具。Prompt 将客户文本和检索文档都标记为不可信数据，模型无工具；引用列表不由模型生成。Prompt Injection 测试确认无 proposal 和 audit 写入。

## Mock、真实 LLM 与调试 API

Mock 模式使用只引用证据的固定说明，不依赖网络。`LLMPolicyAnswerer` 复用现有 OpenAI-compatible Chat Provider，但仅生成标注为“Model-generated explanation (not authorization)”的解释；引用和安全边界仍由服务端生成。自动化测试用捕获型 Mock Provider 验证了 system prompt、证据边界和 `tools=[]`。

当前 `.env` 为 `AGENT_PROVIDER=mock`，虽然有已配置的 DeepSeek 凭据。本次尝试真实 LLM 烟测时，受限环境内网络被阻断，随后外部调用审批明确拒绝把政策片段/合成查询发往该端点。因此本阶段不宣称真实 LLM Policy 回答成功，Token 和成本为缺失。

`POST /api/v1/debug/plan` 现在返回用户输入、Triage、Supervisor 任务、检索查询/关键词/方法/Top-K、分数、完整片段、来源、Policy 回答和共享状态。实例见 README。

## 新增与修改文件

主要新增：

- `backend/app/multi_agent/policy_knowledge.py`、`policy_agent.py`。
- `scripts/index_policy.py`、`scripts/evaluate_policy_retrieval.py`。
- `data/evaluation/policy_retrieval_v1.json`、`reports/phase2_4_retrieval.json`。
- `tests/test_phase24_policy.py`、`test_phase24_api.py`、`test_phase24_postgres.py`。
- `docs/PHASE2_4_REPORT.md`。

主要修改：

- `backend/app/database.py`、`config.py`、`main.py`。
- `backend/app/multi_agent/models.py`、`state.py`、`triage.py`、`workflow.py`。
- `.env.example`、`README.md`、`TASKS.md`、`docs/PHASE2_ARCHITECTURE.md`。

## 验收结果与未完成项

- `.venv312` 完整套件：**125 passed、1 skipped**；唯一跳过为该环境未安装 `tau2`。
- `.venv_tau` 完整套件：**126 passed、0 failed、0 skipped**，包含 PostgreSQL、FastAPI、Order Agent 和单 Agent Baseline 回归。
- `ruff check backend scripts tests`：通过。
- PostgreSQL 集成测试使用随机独立 schema 并在结束后删除；Policy 路径没有 proposal/audit 写入。

当前未完成：pgvector 扩展安装、Embedding Key/实际向量导入、真实 LLM Policy 烟测。这些不影响可测试的关键词闭环，但意味着不能声称向量检索已在当前机器运行。

后续 2.5 需特别注意：Resolution 只能使用服务端已验证的订单摘要与政策证据；不能把 Policy 解释变成资格授权；任何写操作仍要具体摘要、明确确认、执行前重读状态、硬规则、事务、幂等和审计。
