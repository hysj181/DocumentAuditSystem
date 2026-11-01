# 完整审核流程说明

## 1. 目标

第五阶段将前四阶段整合为一条命令行审核流程：

```text
项目一批次 JSON
  -> 输入结构校验
  -> 数学校验
  -> 错别字检查
  -> 审核问题收集（数学 + 错别字）
  -> Word/PDF 定位
  -> Word 红色批注 / PDF 红色矩形标记
  -> 完整 JSON/Markdown 审核报告
```

入口：

```powershell
uv run python main.py audit `
  --batch-json "<batch.json>" `
  --output-dir "output"
```

本阶段不新增审核规则，只接入现有 `math_audit.py` 实际生成的问题。

## 2. 模块调用关系

```text
main.py
  -> pipeline.run_audit()
       -> project1_batch.Project1Batch.load()
       -> pipeline.validate_batch_input()
       -> math_audit.validate_batch()
       -> typo_audit.scan_batch_typos()
       -> pipeline.collect_audit_issues(validation, typo_result)
       -> location.locate_issues()
       -> annotation.annotate_issues()
            -> word_annotator
            -> pdf_annotator
       -> save_validation_result()
       -> 完整 audit_report JSON / Markdown
```

复用的现有模型：

- `AuditIssue`
- `LocationResult`
- `AnnotationResult`
- `AuditReport`
- `MathValidationResult`
- `AnnotationBatchResult`

未重复定义已有模型。

## 3. 输入校验

`pipeline.validate_batch_input()` 检查：

- `batch_id` 非空。
- `environmental` 字段存在且为对象。
- `documents` 非空。
- 每个文档包含：
  - `document_id`
  - `source_file`
  - `file_type` 为 `word` 或 `pdf`
- `document_id` 不重复。

规则：

- `environmental` 缺失或为 `null`：停止审核，抛出 `PipelineInputError`。
- `environmental.records` 存在但为空：允许继续，记录数为 0。
- 源文件路径缺失字段：输入结构错误。
- 源文件在磁盘上不存在：不是结构错误，继续数学审核，但记录警告；定位/批注会进入未找到/人工核实，完整报告不会标记为完整成功。

## 4. 问题收集扩展点

`collect_audit_issues(validation, typo_result)` 是唯一的问题收集入口：

```python
def collect_audit_issues(validation, typo_result=None):
    issues = list(validation.issues)
    if typo_result is not None:
        issues.extend(typo_result.issues)
    return issues
```

当前接入数学校验和错别字检查。未来单位检查、数据缺失检查、外部 AI 错误清单等规则可以在这里追加问题，不需要改动后续定位、批注和报告流程。

## 5. 合成数据隔离

合成测试批次必须在顶层声明：

```json
{
  "metadata": {
    "synthetic_data": true
  }
}
```

行为：

- `Project1Batch.load()` 读取顶层 `metadata`。
- `run_audit()` 仅在 `synthetic_data is True` 时标记合成数据。
- 所有收集到的 `AuditIssue.metadata["synthetic"] = true`。
- Word 批注文本增加 `[合成测试数据]`。
- 完整报告 `metadata.pipeline.synthetic_data = true`。
- 阶段报告和警告中明确提示合成测试数据。

真实项目一批次没有该字段，不会被标记为合成数据。

## 6. 计数定义

完整报告中的 `metadata.pipeline.counts`：

| 字段 | 含义 |
| --- | --- |
| `record_count` | 项目一环境记录数 |
| `verified_count` | 明确表达式已验证且一致 |
| `unverified_count` | 无明确计算表达式，无法验证，不计为错误 |
| `issue_count` | 本次审核收集到的问题数 |
| `located_count` | 定位状态为 `located` 的问题数 |
| `annotation_applied_count` | 批注/标记成功数 |
| `annotation_failed_count` | 批注/标记失败数 |
| `annotation_manual_review_count` | 批注阶段进入人工核实数 |
| `issues_flagged_for_manual_review` | 问题自身 `needs_manual_review = true` 的数量 |

`issues_flagged_for_manual_review` 与 `annotation_manual_review_count` 分开统计，不能合并。

普通监测数值即使没有计算表达式，也只计入 `unverified_count`，不计入 `issue_count`。

错别字检查独立统计：

| 字段 | 含义 |
| --- | --- |
| `typo_issue_count` | 所有错别字问题数，含高/低置信度 |
| `typo_verified_count` | 高置信度错别字问题数 |
| `typo_manual_review_count` | 最终批注状态为 `skipped` 的错别字问题数 |
| `typo_annotation_success_count` | 错别字批注/标记成功数 |
| `typo_annotation_failed_count` | 错别字批注/标记失败数 |

错别字统计位于 `metadata.pipeline.typo_counts`，不改变原 `metadata.pipeline.counts` 结构。

## 7. 阶段状态与完整成功

`metadata.pipeline.stages`：

```text
load
math_validation
typo_audit
location
annotation
```

每个阶段包含状态、计数和报告路径。

`metadata.pipeline.complete_success` 为 `true` 的条件：

- 没有源文件缺失警告；
- 所有问题定位为 `located`；
- 没有批注失败；
- 没有批注阶段人工核实项。

注意：

- `unverified_count > 0` 不会导致 `complete_success = false`，因为无计算表达式是正常状态。
- `issues_flagged_for_manual_review > 0` 不单独导致 `complete_success = false`；该数字单独展示。
- 项目一源文件缺失时 `complete_success = false`，即使数学审核仍可完成。
- 低置信度错别字、定位失败或定位不安全的错别字问题会进入人工核实，并使 `complete_success = false`。

## 8. 报告结构

### 完整 JSON 报告

`audit_report_<batch_id>.json` 使用 `AuditReport` 结构，包含：

- `report_id`
- `batch_id`
- `generated_at`
- `source_batch`
- `documents`
- `summary`
- `issues`
- `annotations`
- `warnings`
- `metadata`
  - `annotation_task`
  - `pipeline`
    - `synthetic_data`
    - `complete_success`
    - `input`
    - `timing`
    - `counts`
    - `typo_counts`
    - `stages`
    - `output_files`
    - `stage_reports`
    - `warnings`
    - `errors`

### 完整 Markdown 报告

`audit_report_<batch_id>.md` 包含：

- 批次、时间、流程完成状态、合成数据标记
- 数量统计
- 错别字检查统计
- 阶段状态
- 输入文件
- 输出文件
- 阶段报告路径
- 审核问题表
- 错别字检查明细（错误原文、建议修改、依据、规则编号、上下文、定位粒度、位置、状态）
- 批注成功清单
- 批注失败清单
- 人工核实清单
- 警告与异常

### 阶段报告

- `<batch_id>_math_validation.json`：数学校验明细。
- `annotation_report_<batch_id>.json/.md`：批注阶段明细。
- `audit_report_<batch_id>.json/.md`：完整审核报告。

所有报告路径使用唯一文件名，重复时自动增加编号。

## 9. Word 批注

- 只处理 `LocationResult.locator_status == "located"` 且 `file_type == "word"` 的问题。
- 正文问题：在目标段落后新增红色批注段落。
- 表格问题：在目标单元格末尾新增红色批注段落。
- 批注以 `#` 开头。
- 同一位置多个问题按输入顺序添加。
- 原始 Word 只读，输出写入 `<output-dir>/annotated/<原名>_annotated.docx`。
- 只使用 `AuditIssue` 的真实描述、原文、建议和已验证计算值。

## 10. PDF 标记

- 只处理 `located` 且 `file_type == "pdf"` 的问题。
- 使用 `LocationResult.page_number` 和 `bbox`。
- 添加红色矩形描边，不填充，避免遮挡原文。
- 页面旋转、无文本层、坐标异常进入人工核实。
- 原始 PDF 只读，输出写入 `<output-dir>/annotated/<原名>_annotated.pdf`。
- 标记前后 PDF 文本提取结果应保持一致。

## 10.1 错别字检查与批注

- 扫描 Word 段落、Word 表格单元格、PDF 文本行和 PDF 表格单元格。
- 使用 `typo_rules.py` 的人工维护词典。
- 只做精确词典匹配和已知正确词的重复字检查，不做拼音自动纠错。
- 保护 P1 企业名称、指标、点位、单位，以及内置专业术语、污染物名称、监测方法名称和标准编号。
- 高置信度问题：`needs_manual_review = false`，可自动批注/标记。
- 低置信度问题：`needs_manual_review = true`，`metadata.auto_annotate = false`，只进入人工核实。
- 同一文本单元多次出现相同错误：只生成一条问题，记录 `occurrence_count` 和多个上下文。
- 不同段落/单元格/PDF 文本位置的问题不合并。
- PDF 使用 P1 文本行或单元格 bbox：
  - 文本行：`location_granularity = "pdf_text_line"`，只标记整行。
  - 表格单元格：`location_granularity = "pdf_table_cell"`。
  - 无可用 bbox：`location_granularity = "pdf_unknown"`，进入人工核实。
- 不直接替换错误文字，只新增批注或标记。

## 11. 异常处理

输入结构错误：

- CLI 返回 2。
- stderr 输出明确错误。
- 不生成审核报告。

源文件缺失：

- 继续数学审核。
- 完整报告记录警告。
- 定位阶段 `not_found`，批注阶段进入人工核实。
- `complete_success = false`。

定位失败：

- 进入 `LocationResult` 的 `ambiguous` / `not_found` / `invalid_location` / `manual_review`。
- 不自动批注。
- 进入完整报告人工核实清单。

批注失败：

- 进入 `AnnotationResult.status = "failed"`。
- 计入 `annotation_failed_count`。
- 进入完整报告批注失败清单。

## 12. 当前限制

- 启用数学计算校验和保守错别字检查，不包含单位检查、数据缺失、合规判断等规则。
- 真实项目一批次可能没有明确计算表达式，此时全部记录为 `unverified`，不产生数学审核问题。
- 错别字检查只覆盖人工确认词典和已知词语重复字，不做任意编辑距离或拼音自动推断。
- 不在保护词、企业名称或标准编号范围内的不熟悉专有名词仍可能需要人工确认。
- 漏字/多字不做无依据的自动推断；只覆盖明确规则和人工确认词典。
- Word 批注是红色文字段落，不是 Word 原生批注。
- Word 定位到段落/单元格，不提供单元格内字符偏移。
- PDF 标记依赖项目一 bbox 和文本层。
- PDF 旋转页和扫描件不自动标记。
- 不开发 GUI。
- 不修改项目一、原始 Word/PDF。
