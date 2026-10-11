# RAG 知识库

这里保存代码审查 RAG 使用的规则源与可复现的数据处理说明。

## 已接入知识源

| source_id | 来源 | 当前版本 | 用途 |
|---|---|---|---|
| `local-review-rules` | 项目自建规则 | 1 | 最小可运行检索集 |
| `mitre-cwe` | MITRE CWE 官方 XML | 4.20 | 漏洞描述、影响、检测、缓解与示例 |
| `owasp-cheatsheet-series` | OWASP 官方 Markdown | Git commit | 应用安全实践与防御方案 |

机器可读的来源信息见 `sources.json`。MITRE CWE 内容受其 Terms of Use 约束；本项目仅保存下载脚本和来源登记，不提交体积较大的原始快照及派生 JSONL。

## CWE 数据流水线

```text
MITRE XML ZIP
  -> 版本化原始快照 + manifest.json + SHA-256
  -> XML 字段解析与文本规范化
  -> description / consequence / detection / mitigation / example 分块
  -> knowledge/normalized/cwe.jsonl
  -> 筛选后调用 embedding
  -> Qdrant
```

下载官方快照：

```bash
python scripts/download_cwe.py
```

生成可追溯分块（版本号按实际下载结果替换）：

```bash
python scripts/build_cwe_chunks.py knowledge/raw/cwe/4.20
```

先查看代码审查子集的规模（不会调用 embedding）：

```bash
python scripts/index_cwe.py
```

确认后分批向量化并写入 Qdrant：

```bash
python scripts/index_cwe.py --write --batch-size 10
```

生成物：

- `knowledge/raw/cwe/<version>/manifest.json`：来源、许可、抓取时间、ZIP/XML SHA-256。
- `knowledge/raw/cwe/<version>/*.xml`：未经改写的官方源文件。
- `knowledge/normalized/cwe.jsonl`：一行一个语义分块，包含规则字段和完整来源元数据。

原始快照和派生数据均在 `.gitignore` 中；这样既避免把大型第三方数据提交进仓库，也能通过脚本、来源 URL、版本和哈希复现同一批数据。

## OWASP Cheat Sheet 流水线

```bash
python scripts/download_owasp_cheatsheets.py
python scripts/build_owasp_chunks.py knowledge/raw/owasp-cheatsheets/<commit>
python scripts/index_owasp.py
python scripts/index_owasp.py --write --batch-size 10
```

下载器先解析官方仓库 `master` 的完整 Git commit，再按 `owasp_review_scope.json` 下载选定 Markdown。切分器识别代码围栏，代码块中的 `#` 不会被误判成标题；正文按标题层级与段落打包，Payload 保存完整 `heading_path`。

## 检索评测

`retrieval_eval_cases.json` 保存查询、语言、分类和人工标注的相关规则 ID。评测按规则 ID 对多个分块去重，计算 Recall@1/3/5、Hit@1/3/5 和 MRR：

```bash
python scripts/evaluate_retrieval.py --output runs/retrieval-eval.json
python scripts/evaluate_retrieval.py --mode hybrid --output runs/retrieval-eval-hybrid.json
```

报告会列出每个样本的首个相关结果排名和 Top5，便于定位未命中样本。评测集和知识库分开维护，禁止根据单次检索结果自动改写标准答案。

混合模式由 Dense 向量召回与本地 BM25 两路组成。BM25 查询先通过通用安全术语表补充中英文概念，再对两路规则级排名使用 RRF 融合。相同 `rule_id` 的多个分块会在截断前去重，防止长文档占据候选窗口。`--dense-weight` 与 `--lexical-weight` 仅用于可记录的开发集实验。

## 分块原则

CWE 是结构化 XML，不按固定字符数粗暴切分。系统先以 `Weakness` 为规则边界，再以安全语义字段为分块边界：

- `description`：弱点定义；
- `consequence`：可能造成的安全影响；
- `detection`：检测方法；
- `mitigation`：缓解措施；
- `example`：示例说明。

同类字段有多项时通过 `ordinal` 保持顺序。`chunk_id` 由来源、CWE 编号、章节、序号、版本组成；`chunk_sha256` 对规范化后的分块内容及元数据计算，因此内容变化可以被发现。
