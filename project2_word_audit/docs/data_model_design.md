# 项目二统一数据模型设计

## 1. 设计目标

项目二的数据模型服务于四个环节：

```text
项目一批次 JSON
      |
      v
审核问题 AuditIssue  <--  外部 AI 审核结果（统一 JSON）
      |
      +--> 计算信息 CalculationInfo
      +--> 原文位置 SourceLocation
      |
      v
审核报告 AuditReport
      |
      v
批注结果 AnnotationResult（下一阶段写回 Word）
```

设计原则：

1. **不编造定位。** 只使用项目一真实存在的 `document_id`、`source_file`、`paragraph_index`、`table_index`、`row_index`、`column_index`、`page_number`、`bbox`。
2. **不混淆置信度。** P1 的 `confidence` 是规则识别置信度；项目二的 `locator_confidence` 专指定位置信度。
3. **正确计算值有门槛。** `CalculationInfo.computed_value` 只有在计算可复现且已验证时才允许非空。
4. **缺失保持缺失。** 无法确定的位置、单位、数值保持 `None`，不用空字符串或 0 代替。
5. **锚点与数值单元格分离。** P1 的 `source_location` 通常指向指标单元格；数值单元格用独立的可选字段表示。
6. **可序列化。** 所有结构支持 `to_dict()` / `from_dict()`，JSON 为唯一主交换格式。

## 2. SourceLocation：原文位置

对应代码：`src/word_audit/models.py::SourceLocation`

| 字段 | 类型 | 必填 | 来源/说明 |
| --- | --- | --- | --- |
| `document_id` | `str` | 是 | P1 `document_id` |
| `source_file` | `str` | 是 | P1 绝对路径，使用前校验存在 |
| `source_name` | `str \| None` | 否 | 文件名 |
| `file_type` | `str` | 否 | `word` / `pdf` |
| `paragraph_index` | `int \| None` | 否 | Word 正文段落序号，0 起 |
| `table_index` | `int \| None` | 否 | 文档内表格序号，0 起 |
| `row_index` | `int \| None` | 否 | 锚点单元格行索引，0 起 |
| `column_index` | `int \| None` | 否 | 锚点单元格列索引，0 起 |
| `value_row_index` | `int \| None` | 否 | 数值单元格行索引，仅在验证后填写 |
| `value_column_index` | `int \| None` | 否 | 数值单元格列索引，仅在验证后填写 |
| `page_number` | `int \| None` | 否 | 仅 PDF 可用；Word 为 `null` |
| `bbox` | `list[float] \| None` | 否 | 仅 PDF 可用；Word 为 `null` |
| `block_index` | `int \| None` | 否 | P1 字段，当前样本为 `null` |
| `reading_order` | `int \| None` | 否 | 仅 PDF 文本行部分有 |
| `source_content_type` | `str` | 否 | `paragraph` / `table` / `ocr_text` 等 |
| `locator_method` | `str` | 否 | `exact_index` / `table_cell` / `text_match` / `manual` / `unknown` |
| `locator_confidence` | `float` | 否 | 0.0–1.0，定位置信度，默认 0.0 |
| `notes` | `list[str]` | 否 | 定位说明，例如“列索引来自表头映射” |
| `metadata` | `dict` | 否 | 扩展信息 |

### 2.1 锚点单元格与数值单元格

真实 P1 样本中：

```text
rows[1] = ["COD", "85", "mg/L", "模拟检测"]
environmental.source_location = {row_index: 1, column_index: 0}
```

`column_index = 0` 指向 `"COD"`，不是 `"85"`。因此：

- `row_index` / `column_index`：P1 给出的锚点，通常是指标单元格，必须原样保留；
- `value_row_index` / `value_column_index`：项目二在表头/列映射可靠验证后填写，否则保持 `None`。

不得为了让“数值单元格”看起来存在而复制 `column_index` 到 `value_column_index`。

### 2.2 定位置信度建议

| 定位方式 | 建议值 | 说明 |
| --- | --- | --- |
| Word 段落索引直接命中 | 0.95–1.0 | `paragraph_index` + 文本核对一致 |
| Word 表格单元格索引直接命中 | 0.9–0.95 | 需核对 `rows[row][col]` 文本 |
| Word 数值单元格由表头映射 | 0.6–0.8 | 表头明确且行文本一致时；否则更低 |
| PDF 表格单元格 | 0.9–0.95 | 还需考虑 OCR 结构误差 |
| PDF 文本行 bbox | 0.7–0.9 | 无段落索引 |
| 仅文本搜索匹配 | 0.4–0.7 | 可能有重复文本 |
| 手工指定 | 1.0 | 需记录 `notes` |
| 无法定位 | 0.0 | `locator_method = "unknown"` |

这些是设计建议，不是对真实定位准确率的实测结论。

### 2.3 校验规则

- `document_id`、`source_file` 非空；
- 所有索引为整数或 `None`；
- `bbox` 必须为 4 个数或 `None`；
- `locator_confidence` 必须在 0–1；
- 当 `locator_method` 不是 `unknown` 或置信度大于 0 时，至少要有 `paragraph_index`、`table_index`、`page_number` 之一。

## 3. CalculationInfo：计算信息

对应代码：`CalculationInfo`、`CalculationOperand`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `formula` | `str \| None` | 计算公式，例如 `(进水-出水)/进水×100%` |
| `substituted_formula` | `str \| None` | 代入数值后的公式 |
| `operands` | `list[CalculationOperand]` | 参与计算的输入项 |
| `reported_value` | `float \| str \| None` | 文档中的原始计算值/报告值 |
| `computed_value` | `float \| None` | 项目二验证后的正确值；未验证必须为 `None` |
| `unit` | `str \| None` | 结果单位 |
| `rounding` | `str \| None` | 舍入规则，如“保留两位小数” |
| `tolerance` | `float \| None` | 允许误差 |
| `verification_status` | `str` | `not_attempted` / `verified` / `failed` / `error` |
| `verification_method` | `str \| None` | 如 `decimal`、`fraction`、`manual` |
| `verification_detail` | `str \| None` | 验证过程或失败原因 |
| `verified_at` | `str \| None` | 验证时间，UTC ISO |
| `notes` | `list[str]` | 补充说明 |
| `metadata` | `dict` | 扩展信息 |

`CalculationOperand`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | `str` | 输入项名称 |
| `numeric_value` | `float \| None` | 用于计算的数值 |
| `raw_value` | `str \| None` | 原文表达 |
| `unit` | `str \| None` | 单位 |
| `source_location` | `SourceLocation \| None` | 输入项来源 |
| `metadata` | `dict` | 扩展信息 |

### 3.1 正确计算值的硬性约束

代码强制：

```text
computed_value 非空  => verification_status 必须是 "verified"
verification_status == "verified" => computed_value 必须非空
```

并且 `verified` 会自动补 `verified_at`。

这保证：

- 外部 AI 不能直接给一个“正确值”却不说明验证状态；
- 未完成可靠计算的审核问题，`computed_value` 保持 `None`；
- 审核问题中的“原始计算值”和“正确计算值”不会互相覆盖。

## 4. AuditIssue：审核问题

对应代码：`AuditIssue`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `issue_id` | `str` | 是 | 问题编号，批次内唯一 |
| `issue_type` | `str` | 是 | 问题类型，建议值见下 |
| `description` | `str` | 是 | 错误描述 |
| `severity` | `str` | 否 | `info` / `warning` / `error`，默认 `warning` |
| `original_text` | `str` | 否 | 原文内容 |
| `location` | `SourceLocation \| None` | 否 | 原文位置；为空则必须人工核实 |
| `calculation` | `CalculationInfo \| None` | 否 | 计算信息 |
| `needs_manual_review` | `bool` | 否 | 是否需要人工核实，默认 `true` |
| `review_reasons` | `list[str]` | 否 | 需人工核实的原因 |
| `suggestion` | `str \| None` | 否 | 修改建议 |
| `status` | `str` | 否 | `open` / `confirmed` / `dismissed` |
| `metadata` | `dict` | 否 | 扩展信息 |

建议 `issue_type`：

```text
calculation_error  计算错误
formula_error      公式错误
value_mismatch     数值不一致
unit_mismatch      单位问题
missing_data       数据缺失
data_inconsistency 数据前后不一致
text_inconsistency 文字表述不一致
other              其他
```

代码保留字符串类型，不强制封闭枚举，便于后续扩展；但写入 JSON 时应使用上述值或明确的自定义值。

### 4.1 需求字段映射

| 要求 | 模型字段 |
| --- | --- |
| 问题编号 | `issue_id` |
| 问题类型 | `issue_type` |
| 错误描述 | `description` |
| 原文内容 | `original_text` |
| 计算公式 | `calculation.formula` |
| 原始计算值 | `calculation.reported_value` |
| 正确计算值 | `calculation.computed_value`（仅 `verified` 时非空） |
| 段落索引 | `location.paragraph_index` |
| 表格索引 | `location.table_index` |
| 行索引 | `location.row_index` |
| 列索引 | `location.column_index` |
| 页码 | `location.page_number` |
| 定位置信度 | `location.locator_confidence` |
| 是否需要人工核实 | `needs_manual_review` |

同时提供只读便捷属性 `formula`、`reported_value`、`computed_value`、`location_confidence`、`is_calculation_verified`，避免重复存储。

### 4.2 无位置问题

外部 AI 可能只给出文字问题、无法定位。此时：

- `location = None`；
- `needs_manual_review` 必须为 `true`；
- 自动追加 `review_reasons = ["location_missing"]`。

## 5. AnnotationResult：批注结果

对应代码：`AnnotationResult`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `annotation_id` | `str` | 批注唯一 ID |
| `issue_id` | `str` | 对应审核问题 |
| `document_id` | `str` | 目标文档 |
| `comment_text` | `str` | 写入 Word 的批注文本 |
| `anchor` | `SourceLocation` | 批注锚点 |
| `status` | `str` | `pending` / `applied` / `failed` / `skipped` |
| `applied_at` | `str \| None` | 成功写入时间 |
| `word_anchor` | `dict \| None` | 实际使用的 Word 定位信息 |
| `error` | `str \| None` | 失败原因 |
| `metadata` | `dict` | 扩展信息 |

约束：

- `anchor.document_id` 必须等于 `document_id`；
- `status = "applied"` 时自动补 `applied_at`；
- 本阶段只定义结构，**不修改 Word，不写批注**。

`word_anchor` 预留记录实际落点，例如：

```json
{
  "paragraph_index": 3,
  "table_index": null,
  "row_index": null,
  "column_index": null,
  "matched_text": "COD 85 mg/L",
  "match_start": 0,
  "match_end": 10
}
```

字符偏移只有在下一阶段实际匹配成功后才写入，不能提前编造。

## 6. AuditReport：审核报告

对应代码：`AuditReport`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema_version` | `str` | 当前 `"1.0"` |
| `report_id` | `str` | 报告唯一 ID |
| `batch_id` | `str \| None` | 对应 P1 批次 |
| `generated_at` | `str` | 生成时间，UTC ISO |
| `source_batch` | `str \| None` | P1 批次 JSON 路径 |
| `documents` | `list[dict]` | 文档摘要，至少含 `document_id`、`source_name`、`source_file`、`file_type` |
| `issues` | `list[AuditIssue]` | 审核问题 |
| `annotations` | `list[AnnotationResult]` | 批注结果 |
| `warnings` | `list[str]` | 报告级警告 |
| `metadata` | `dict` | 扩展信息 |

`summary()` 自动生成：

```json
{
  "issue_count": 0,
  "annotation_count": 0,
  "needs_manual_review_count": 0,
  "verified_calculation_count": 0,
  "by_severity": {"info": 0, "warning": 0, "error": 0},
  "by_type": {},
  "annotations_by_status": {
    "pending": 0, "applied": 0, "failed": 0, "skipped": 0
  }
}
```

`validate()` 检查：

- `issue_id` 不重复；
- `annotation_id` 不重复；
- 每条批注引用的 `issue_id` 存在。

## 7. 统一的错误清单

对应代码：`src/word_audit/error_list.py::ErrorList`

`ErrorList` 是外部 AI 与项目二之间的输入契约：

```text
schema_version, batch_id, generated_at, issue_count,
source, issues[], metadata
```

详细 JSON 格式见 `docs/error_list_format.md`。

`ErrorList.to_report(...)` 可将错误清单转为 `AuditReport`，批注结果在下一阶段追加。

## 8. 与项目一字段的对应关系

| 项目二字段 | 项目一来源 |
| --- | --- |
| `SourceLocation.document_id` | `documents[].document_id` / `records[].document_id` |
| `SourceLocation.source_file` | `documents[].source_file` / `environmental.records[].source_file` |
| `SourceLocation.paragraph_index` | `records[].location.paragraph_index` |
| `SourceLocation.table_index` | `records[].location.table_index` 或 `environmental.records[].source_location.table_index` |
| `SourceLocation.row_index` | `records[].metadata.cells[].row_index` 或 `environmental...source_location.row_index` |
| `SourceLocation.column_index` | 同上（注意是指标锚点列） |
| `SourceLocation.page_number` | PDF 的 `location.page_number`；Word 无 |
| `SourceLocation.bbox` | PDF 的 `location.bbox` / `cells[].bbox`；Word 无 |
| `AuditIssue.original_text` | `records[].text`、`source_text`、`raw_expression` |
| `CalculationInfo.reported_value` | `environmental.records[].value`（仅作为报告值，不作为正确值） |
| `CalculationInfo.unit` | `environmental.records[].unit`（可能是规范化单位） |
| `CalculationOperand.source_location` | 对应输入项的位置 |

## 9. 项目一限制在设计中的体现

| 项目一限制 | 项目二设计应对 |
| --- | --- |
| Word 无页码/坐标 | `SourceLocation.page_number/bbox` 允许 `None`，Word 批注只依赖段落/表格索引 |
| Word 表格不在 `tables[]` | 读取时从 `records[].metadata.rows` 取表格，不使用 `document.table_count` |
| Word 表格无表头字段 | 表头推断结果写入 `location.notes`，并降低定位置信度 |
| 环境记录列索引指向指标单元格 | 增加 `value_row_index/value_column_index`，仅在验证后填写 |
| 单位被规范化 | `CalculationInfo.unit` 记录审计使用的单位，`original_text` 保留原文 |
| 环境记录无可靠计算值 | `computed_value` 默认 `None`，验证后才写 |
| 绝对路径可能失效 | 使用前校验 `source_file` 存在 |
| 无字符级偏移 | `SourceLocation` 只到单元格；字符偏移只放在批注阶段的 `word_anchor` |

## 10. 序列化与版本

- 当前 `SCHEMA_VERSION = "1.0"`。
- 所有结构提供 `to_dict()` / `from_dict()`。
- `ErrorList` 拒绝非 `"1.0"` 的 `schema_version`，避免静默读入不兼容数据。
- JSON 使用 UTF-8、`ensure_ascii=False`、2 空格缩进。
- `None` 原样序列化为 `null`，不转成空字符串或 0。
