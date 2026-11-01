# 阶段 0 数据结构与导入方案

本报告基于实际下载和校验，不根据历史数据猜测字段。上游固定版本为 `da0835f6c67baef58bdda18f2a3b037dfb3a1754`，来源为 https://github.com/sierra-research/tau2-bench 。完整来源 URL、UTC 获取时间、大小与 SHA256 在原始目录的 `manifest.json`。

## 实际结构

| 集合 | 数量 | 实际字段 |
|---|---:|---|
| users（ID → 对象） | 500 | user_id、name（first_name/last_name）、email、address、payment_methods（字典）、orders（ID 列表） |
| products（ID → 对象） | 50 | product_id、name、variants（item_id → 变体） |
| orders（ID → 对象） | 1000 | order_id、user_id、address、items（列表）、status、fulfillments、payment_history |

共有 591 个商品变体、2,978 个订单商品条目。变体有 item_id、options、available、price；订单商品有 item_id、product_id、name、options、price，**无 quantity 字段**，不得自行补为源数据事实。订单价格是历史快照，不能替换为商品当前价格。初始订单状态实际出现 pending、processed、delivered、cancelled。

`policy.md` 为 6,699 字节、12 个 Markdown 标题，包含身份约束、通用操作、取消、修改、退货和换货规则。政策不是授权实现。政策中修改商品后的状态写作 `pending (items modifed)`，模型写作 `pending (item modified)`；阶段 0 未进行任何业务写动作，阶段 1 必须以同版本 `tools.py` 实际行为核验并显式映射，不能按自然语言猜测状态值。

检查脚本只输出字段名、类型、数量、政策标题；不输出用户 ID、姓名、邮箱、地址、支付方式或具体订单。tasks/split 文件下载并记录哈希，检查/导入不读取评测参考动作与评分条件，业务 API 不加载原始目录。

## 第一版存储与约束

| 表 | 提取字段 | JSONB 保留 |
|---|---|---|
| users | source_user_id（主键） | profile_json：完整源用户对象 |
| products | source_product_id（主键）、name | product_json：完整源商品与变体 |
| orders | source_order_id（主键）、source_user_id（外键及索引）、status、row_version | order_json：完整源订单与商品/履约/支付历史 |
| import_state | 单例 id、source_hash | 无 |

Pydantic 严格校验基本字段类型，允许额外字段以保留上游扩展；不声称这是上游全部嵌套支付/履约模型的完全重实现。进一步校验字典键/对象 ID、变体全局唯一性、非负价格、订单归属双向一致、商品与变体引用和已知状态。验证失败在事务前停止，日志不包含原始记录。未引入 tickets、审计表或向量库。

SQLAlchemy 在 PostgreSQL 使用 JSONB，SQLite 只在测试时使用 JSON；演示 CLI 拒绝 SQLite。事务内按 orders → products → users 删除，再按相反依赖顺序插入；失败整体回滚。PostgreSQL 事务 advisory lock 串行化种子数据操作。表结构创建独立于数据事务，不是版本迁移系统，后续结构变更需要迁移机制。

相同 db.json 哈希重复导入：不新增、不覆盖现有业务状态，只核对行数。不同哈希拒绝隐式替换，必须显式 `--reset`。行数异常拒绝声称导入成功。`--reset` 删除演示表中的现有数据并恢复此源版本；其他后续业务表尚不存在。数据库名必须以 `_demo` 结尾；这是操作防误用约束，不能替代物理隔离、独立凭据或部署授权。

原始文件不被检查/导入脚本修改；已有下载只验哈希，不覆盖，发现损坏即失败。用户应保留源文件及 manifest，不手动修改；重新获取应使用新的目标目录。哈希用于完整性与溯源，不是上游签名认证。

## 许可与隔离

已下载的仓库根 LICENSE 为 MIT、署名 Copyright (c) 2025 Sierra Research，保存在原始版本目录；脚本同时保留完整许可证。未核实存在额外数据专属许可，不能仅据根许可证推断所有数据再分发权；因此不提交/分发原始数据和上游源码。上游模型/工具仅本地勘察，不作为应用依赖或直接复制到业务层。

演示库只包含 users/products/orders 的模拟业务状态；tasks/split 只位于本地受控原始目录，不写入业务库、RAG、API 或 Agent。当前无官方评测运行；以后需使用独立数据库/进程/凭据。
