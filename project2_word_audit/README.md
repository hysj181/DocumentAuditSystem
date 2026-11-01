# 企业环境数据智能审核系统（project2_word_audit）

`project2_word_audit` 是一个 Windows 环境下运行的命令行工具，用于读取项目一的批次 JSON，检查企业环境监测数据中的明确数学表达式问题，定位原始 Word/PDF 位置，并生成审核报告与批注副本。

当前版本不包含 GUI，不修改项目一代码或数据，也不修改原始 Word/PDF。

## 功能概览

- 读取项目一 `schema_version = "1.0"` 的 `batch.json`。
- 校验批次必要结构。
- 识别明确的数学计算表达式并校验计算结果。
- 不把普通监测数值误判为计算错误。
- 使用保守词典检查常见中文错别字、明显重复字和已知文字错误。
- 保护专业术语、污染物名称、企业名称、标准编号和监测方法名称，避免简单误报。
- 将审核问题定位到 Word 段落/表格单元格或 PDF 页面 bbox。
- 仅对 `located` 问题写入批注或标记。
- Word：在段落之后或表格单元格内新增红色文字批注。
- PDF：在页面对应区域添加红色矩形描边，不遮挡原文。
- 生成完整 JSON/Markdown 审核报告，以及数学校验、批注阶段明细报告。
- 输出文件重复时自动增加编号，不覆盖已有文件。
- 保留 `validate-batch` 命令，用于只做数学校验。

## 环境要求

- Windows 10/11
- Python 3.12
- [uv](https://docs.astral.sh/uv/) 0.13 及以上

## 安装

```powershell
cd D:\DocumentAuditSystem\project2_word_audit
uv sync
```

依赖：

- `python-docx`
- `pymupdf<2`

## CLI 命令

### 完整审核

```powershell
uv run python main.py audit `
  --batch-json "D:\DocumentAuditSystem\project1_extraction\output\batches\20261101T053459830362Z_0e022780\batch.json" `
  --output-dir "output"
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--batch-json` | 是 | 项目一批次 JSON 路径 |
| `--output-dir` | 否 | 输出根目录，默认 `output` |
| `--help` | - | 查看完整帮助 |

行为：

- 完整审核结束后打印批次、记录数、verified/unverified、问题数、定位数、批注成功/失败/人工核实数、错别字统计、报告路径。
- 输入路径或 JSON 结构错误返回退出码 `2`，并在 stderr 输出明确错误。
- 其他运行错误返回退出码 `1`。
- 正常完成返回 `0`，即使存在审核问题或人工核实项。

### 仅数学校验

```powershell
uv run python main.py validate-batch `
  --batch-json "D:\DocumentAuditSystem\project1_extraction\output\batches\20261101T053459830362Z_0e022780\batch.json"
```

`validate-batch` 还支持 `--output <路径>` 指定数学校验报告路径；省略时写入
`output/reports/<batch_id>_math_validation.json`。

### 查看帮助

```powershell
uv run python main.py --help
uv run python main.py audit --help
uv run python main.py validate-batch --help
```

## 输入 JSON 格式

完整审核读取项目一标准批次 JSON，当前仅支持 `schema_version = "1.0"`。

必要结构：

```json
{
  "schema_version": "1.0",
  "batch_id": "批次 ID",
  "documents": [
    {
      "document_id": "文档 ID",
      "source_name": "原文件名",
      "source_file": "原始文件绝对路径",
      "file_type": "word",
      "records": []
    }
  ],
  "environmental": {
    "records": []
  }
}
```

规则：

- `batch_id`、`documents`、`environmental` 必须存在。
- `environmental` 字段缺失或不是对象时停止审核并报错。
- `environmental.records` 可以为空，空记录允许继续。
- 每个文档必须有 `document_id`、`source_file`、有效期 `file_type`（`word` / `pdf`）。
- 项目一源文件不存在时继续数学审核，但会在报告中记录源文件警告，且不会报告为完整成功。
- 合成测试批次必须使用顶层标记：

```json
{
  "metadata": {
    "synthetic_data": true
  }
}
```

真实项目一批次没有该字段。合成标记会进入完整报告、阶段报告和 Word 批注内容，避免与真实审核结果混淆。

## 输出文件结构

```text
<output-dir>/
├── annotated/
│   ├── <原文件名>_annotated.docx
│   └── <原文件名>_annotated.pdf
└── reports/
    ├── audit_report_<batch_id>.json
    ├── audit_report_<batch_id>.md
    ├── annotation_report_<batch_id>.json
    ├── annotation_report_<batch_id>.md
    └── <batch_id>_math_validation.json
```

说明：

- `audit_report`：完整审核报告，包含各阶段统计、输入/输出文件、问题、批注结果、警告。
- `annotation_report`：第四阶段批注阶段明细报告。
- `<batch_id>_math_validation.json`：第二阶段数学校验明细。
- 只有存在可批注问题时才会生成 `annotated/` 下的副本。
- 文件同名时自动追加 `_1`、`_2`，不覆盖已有输出。

## 错别字检查

- 使用 `src/word_audit/typo_rules.py` 中的人工维护词典。
- 当前只做精确词典匹配和已知词语重复字检查，不做拼音自动纠错，不做编辑距离猜词。
- 高置信度问题自动进入定位和批注流程。
- 低置信度问题生成审核问题，但设置 `auto_annotate = false`，只进入人工核实，不自动批注。
- 专业术语、污染物名称、企业名称、标准编号、监测方法名称受保护。
- 每条问题保留错误原文、建议修改、上下文、判断依据、规则编号、来源位置和定位粒度。
- PDF 只有整行 bbox 时只标记整行，并在报告中记录 `pdf_text_line`，不声称精确定位到单个汉字。
- 同一段落或单元格出现多次相同错误时，记录 `occurrence_count`，不同位置的问题不会合并。

完整报告新增：

```text
metadata.pipeline.typo_counts
├── typo_issue_count
├── typo_verified_count
├── typo_manual_review_count
├── typo_annotation_success_count
└── typo_annotation_failed_count
```

## 审核状态

数学校验：

| 状态 | 含义 |
| --- | --- |
| `verified` | 明确表达式已计算且与报告值一致 |
| `unverified` | 没有明确计算表达式，无法验证，不计为错误 |
| `error` | 明确表达式计算结果与报告值不一致，生成审核问题 |

定位：

| 状态 | 含义 |
| --- | --- |
| `located` | 索引/坐标及原文文本核对通过 |
| `ambiguous` | 存在多个候选位置 |
| `not_found` | 目标位置或源文件不存在 |
| `invalid_location` | 索引/坐标无效 |
| `manual_review` | 需要人工确认 |

批注：

| 状态 | 含义 |
| --- | --- |
| `applied` | 已写入批注或标记 |
| `failed` | 写入失败 |
| `skipped` | 因定位未通过或条件不安全，进入人工核实 |

错别字问题：

| 字段 | 含义 |
| --- | --- |
| `issue_type = "typo"` | 错别字问题 |
| `typo_confidence = "high"` | 高置信度，可自动批注 |
| `typo_confidence = "low"` | 低置信度，只进入人工核实 |
| `auto_annotate = false` | 不允许自动批注/标记 |

完整报告分别统计：

- `unverified_count`
- `issue_count`
- `located_count`
- `annotation_applied_count`
- `annotation_failed_count`
- `annotation_manual_review_count`
- `issues_flagged_for_manual_review`

`issues_flagged_for_manual_review` 是问题级标记，`annotation_manual_review_count` 是批注阶段人工核实数量，两者不合并。

## 安全与只读

- 项目一代码、批次 JSON、原始 Word/PDF 均只读。
- 所有批注和标记只写入新副本。
- 不覆盖已有输出。
- 无法定位的问题不强行批注。
- 未验证的计算结果不写入确定结论。
- 不把普通监测数值认定为计算错误。
- 真实批次与合成测试数据严格区分。

## 当前限制

- 当前启用数学计算校验和保守中文错别字检查，不包含单位错误、数据缺失、合规判断等规则。
- 只识别明确的算术表达式，不推断隐式计算。
- 错别字检查只覆盖人工确认词典和已知词语重复字，不做任意编辑距离或拼音自动推断。
- 不熟悉的专有名词如果不在保护词、企业名称或标准编号规则内，仍可能需要人工确认。
- 漏字、多字的自动识别仅限明确规则；不做无依据的补字或改词。
- 真实样本批次可能没有计算表达式，此时记录为 `unverified`，不会生成审核问题。
- Word 批注是红色文字段落，不是 Word 原生批注/修订记录。
- Word 只能定位到段落/表格单元格，不能定位到单元格内字符偏移。
- PDF 标记为红色矩形描边，依赖项目一 bbox 和 PDF 文本层。
- PDF 页面旋转、无文本层扫描件会进入人工核实。
- 不开发 GUI。

## 测试

```powershell
uv run python -m unittest discover -s tests -v
```

真实批次测试只读；合成测试使用临时目录，并带有 `metadata.synthetic_data = true` 标记。

## 相关文档

- `docs/project1_data_analysis.md`
- `docs/data_model_design.md`
- `docs/error_list_format.md`
- `docs/location_rules.md`
- `docs/pipeline.md`
- `docs/typo_rules.md`
