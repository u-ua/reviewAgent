# ReviewAgent

> 一个证据驱动、权限隔离、过程可追溯的多 Agent 代码审查 Runtime。

ReviewAgent 是一个 Python 3.11+ 作品集项目。它把基于大模型的代码审查拆成可审计的工作流：Planner 负责规划任务图，Executor 在受限工具箱内读取代码和提交 Finding；每个 Finding 都要保留源码或规则证据，整个过程会写入可复盘的执行账本。

## 项目要解决的问题

很多 Agent Demo 能给出“结论”，但说不清模型实际读了什么、为什么有权限读、报出的行号是否有证据支撑。本项目关注这些工程约束：

- **最小权限分工**：Planner 只能提交任务图命令；Executor 仅有只读代码工具，以及 Finding/任务结果提交工具。
- **行号证据门卫**：Finding 必须引用覆盖对应文件和行号范围的源码 Artifact；启用 RAG 时，安全类 Finding 还必须提供规则证据。
- **路径安全**：所有文件工具在 realpath 解析后校验仓库范围，拒绝绝对路径、`..`、`.env` 与 `.git`。
- **可审计状态**：工具调用和提交记录追加到 `execution.jsonl`；报告与指标均从该账本投影生成。
- **依赖感知的有限并发**：Controller 原子领取已就绪任务，并用默认大小为 2 的线程池运行相互独立的 Executor；Planner 决策始终串行。

## 架构

```text
CLI
 └─ ReviewController
     ├─ Planner：planner_submit → 校验并更新任务图
     ├─ TaskStore：原子领取依赖已满足的任务，并标记为 running
     └─ Executor 线程池：只读工具 / finding_write / task_result_submit
          ├─ ArtifactStore：以 SHA-256 内容寻址保存源码、规则证据
          ├─ FindingStore：校验证据与行号范围
          └─ ExecutionLog：追加式 execution.jsonl

可选 RAG：规则查询 → 向量检索 + BM25 → RRF 融合 → 规则证据 Artifact
```

## 技术栈

- Python 3.11+；使用标准库 `urllib` 调用 OpenAI 兼容模型接口
- Qdrant Client 负责向量检索；手写 BM25 与 RRF（倒数排名融合）
- pytest 覆盖 Runtime、证据门卫、检索、报告与本地工作台
- 不依赖 Agent 编排框架：工具 Schema、业务校验、重试和状态持久化均在代码中显式实现

## 快速开始

```bash
# 创建虚拟环境并安装项目与开发依赖
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"

# 运行自动化测试
.venv\Scripts\python -m pytest -q --basetemp .tmp/pytest

# 跑离线、可复现的演示仓库；不需要 API Key
.venv\Scripts\python -m review_agent --repo fixtures/demo-repo --scope src \
  --goal "审查演示仓库中的代码质量与安全问题" \
  --provider fake --max-cycles 6 --cases fixtures/cases.json

# 根据一次已完成的运行生成只读审计报告
.venv\Scripts\python scripts/generate_report.py runs/<session-id>

# 浏览本地运行报告，仅监听 localhost
.venv\Scripts\python -m review_agent.web
```

本次发布已在项目内临时目录验证 `76 passed`；离线 fake provider 在预设的 8 个案例中完成 8/8 命中。该 provider 只用于保证演示流程可复现，**不代表真实模型效果**。如需连接兼容模型，将 `.env.example` 复制为本地 `.env`，配置变量后使用 `--provider openai`。

## RAG 与知识源

仓库只保留规则定义、来源元数据和评测案例；原始 CWE/OWASP 快照、归一化结果、Qdrant 数据、密钥和运行产物均留在本地。需要时可显式重建：

```bash
.venv\Scripts\python scripts/download_cwe.py
.venv\Scripts\python scripts/build_cwe_chunks.py knowledge/raw/cwe/<version>
.venv\Scripts\python scripts/download_owasp_cheatsheets.py
.venv\Scripts\python scripts/build_owasp_chunks.py knowledge/raw/owasp-cheatsheets/<commit>
.venv\Scripts\python scripts/index_rules.py
```

知识源归属、导入边界和检索评测格式见 [knowledge/README.md](knowledge/README.md)。

## 目录结构

```text
review_agent/       Runtime：Controller、角色、工具、存储、RAG 与本地工作台
fixtures/           可复现的演示仓库与预期 Finding
knowledge/          规则元数据、来源清单与评测案例
scripts/            评测、报告、索引及知识源导入脚本
tests/              自动化回归测试
```

## 当前边界

这是本地 Runtime，不是托管式代码审查服务：目前不包含 GitHub PR 评论、执行不可信代码的沙箱、分布式调度或故障恢复。有限线程池仅在单进程中重叠独立的 I/O 等待，不等同于分布式执行。

## 许可证

MIT，见 [LICENSE](LICENSE)。
