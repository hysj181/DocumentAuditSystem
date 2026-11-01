# 统一错误清单 JSON 格式（schema_version = 1.0）

## 1. 用途

统一错误清单是项目二与外部审核引擎 / 外部 AI 之间的数据交换格式：

- 项目二内部审核器输出该格式；
- 外部 AI 审核结果按该格式导入；
- 项目二校验定位后，生成 `AuditReport`；
- 下一阶段根据问题位置生成 `AnnotationResult` 并写入 Word。

## 2. 顶层结构

```json
{
  "schema_version": "1.0",
  "batch_id": "20261101T053459830362Z_0e022780",
  "generated_at": "2026-11-01T06:00:00+00:00",
  "issue_count": 1,
  "source": {
    "batch_json": "D:\\DocumentAuditSystem\\project1_extraction\\output\\batches\\20261101T053459830362Z_0e022780\\batch.json",
    "producer": "external-ai",
    "model": "example-model"
  },
  "issues": [],
  "metadata": {}
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema_version` | `str` | 是 | 必须为 `"1.0"` |
| `batch_id` | `str \| null` | 否 | 对应项目一批次 |
| `generated_at` | `str` | 否 | UTC ISO 时间，缺省由读取方补齐 |
| `issue_count` | `int` | 否 | 便于人工检查；以 `issues` 数组长度为准 |
| `source` | `object` | 否 | 数据来源、生产方、模型等 |
| `issues` | `array` | 是 | 审核问题数组，可为空 |
| `metadata` | `object` | 否 | 扩展信息 |

## 3. 问题对象

```json
{
  "issue_id": "issue-0001",
  "issue_type": "calculation_error",
  "severity": "error",
  "description": "报告中计算结果与代入值不一致。",
  "original_text": "COD 85 mg/L，去除率 12.5%",
  "location": {
    "document_id": "19353a83da7e47c1b236f87ff7036c71",
    "source_file": "D:\\DocumentAuditSystem\\project1_extraction\\test_data\\01_企业废水监测报告.docx",
    "source_name": "01_企业废水监测报告.docx",
    "file_type": "word",
    "paragraph_index": null,
    "table_index": 0,
    "row_index": 1,
    "column_index": 0,
    "value_row_index": 1,
    "value_column_index": 1,
    "page_number": null,
    "bbox": null,
    "block_index": null,
    "reading_order": null,
    "source_content_type": "table",
    "locator_method": "table_cell",
    "locator_confidence": 0.95,
    "notes": ["列索引 0 为指标锚点，数值列 1 由表头“监测结果”映射并核对。"],
    "metadata": {}
  },
  "calculation": {
    "formula": "去除率 = (进水浓度 - 出水浓度) / 进水浓度 × 100%",
    "substituted_formula": "(100 - 85) / 100 × 100%",
    "operands": [
      {
        "name": "进水浓度",
        "numeric_value": 100.0,
        "raw_value": "100",
        "unit": "mg/L",
        "source_location": null,
        "metadata": {}
      },
      {
        "name": "出水浓度",
        "numeric_value": 85.0,
        "raw_value": "85",
        "unit": "mg/L",
        "source_location": null,
        "metadata": {}
      }
    ],
    "reported_value": 12.5,
    "computed_value": 15.0,
    "unit": "%",
    "rounding": "保留一位小数",
    "tolerance": 0.1,
    "verification_status": "verified",
    "verification_method": "decimal",
    "verification_detail": "(100-85)/100*100 = 15.0",
    "verified_at": "2026-11-01T06:00:00+00:00",
    "notes": [],
    "metadata": {}
  },
  "needs_manual_review": false,
  "review_reasons": [],
  "suggestion": "请核对去除率计算。",
  "status": "open",
  "metadata": {}
}
```

> 示例中的数值仅用于展示格式，不代表本次项目一样本的真实审核结论。

### 3.1 问题字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `issue_id` | `str` | 是 | 批次内唯一 |
| `issue_type` | `str` | 是 | 见 3.2 |
| `severity` | `str` | 否 | `info` / `warning` / `error`，默认 `warning` |
| `description` | `str` | 是 | 错误描述 |
| `original_text` | `str` | 否 | 原文内容 |
| `location` | `object \| null` | 否 | 原文位置；为空时必须人工核实 |
| `calculation` | `object \| null` | 否 | 计算信息 |
| `needs_manual_review` | `bool` | 否 | 默认 `true` |
| `review_reasons` | `array[str]` | 否 | 需人工核实原因 |
| `suggestion` | `str \| null` | 否 | 修改建议 |
| `status` | `str` | 否 | `open` / `confirmed` / `dismissed`，默认 `open` |
| `metadata` | `object` | 否 | 扩展信息 |

### 3.2 问题类型

```text
calculation_error   计算错误
formula_error       公式错误
value_mismatch      数值不一致
unit_mismatch       单位问题
missing_data        数据缺失
data_inconsistency  数据前后不一致
text_inconsistency  文字表述不一致
other               其他
```

允许自定义值，但应在 `metadata` 中说明。

## 4. 位置对象

### 4.1 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `document_id` | `str` | 是 | 必须能在 P1 批次中找到 |
| `source_file` | `str` | 是 | 应与 P1 `source_file` 一致 |
| `source_name` | `str \| null` | 否 | 文件名 |
| `file_type` | `str` | 否 | `word` / `pdf` |
| `paragraph_index` | `int \| null` | 否 | Word 段落索引 |
| `table_index` | `int \| null` | 否 | 表格索引 |
| `row_index` | `int \| null` | 否 | 锚点行索引 |
| `column_index` | `int \| null` | 否 | 锚点列索引 |
| `value_row_index` | `int \| null` | 否 | 数值单元格行，仅验证后填写 |
| `value_column_index` | `int \| null` | 否 | 数值单元格列，仅验证后填写 |
| `page_number` | `int \| null` | 否 | 仅 PDF 可用 |
| `bbox` | `array[float] \| null` | 否 | 仅 PDF 可用，4 个数 |
| `block_index` | `int \| null` | 否 | P1 扩展字段 |
| `reading_order` | `int \| null` | 否 | PDF 文本行顺序 |
| `source_content_type` | `str` | 否 | `paragraph` / `table` / `ocr_text` 等 |
| `locator_method` | `str` | 否 | `exact_index` / `table_cell` / `text_match` / `manual` / `unknown` |
| `locator_confidence` | `float` | 否 | 0.0–1.0 |
| `notes` | `array[str]` | 否 | 定位说明 |
| `metadata` | `object` | 否 | 扩展信息 |

### 4.2 不同来源的最小定位要求

| 来源 | 最小要求 |
| --- | --- |
| Word 段落 | `document_id` + `source_file` + `paragraph_index` |
| Word 表格整体 | `document_id` + `source_file` + `table_index` |
| Word 表格单元格 | 再加 `row_index` + `column_index` |
| Word 数值单元格 | `value_row_index` + `value_column_index`，且需在 `notes` 说明映射依据 |
| PDF 表格单元格 | `document_id` + `source_file` + `page_number` + `table_index` + `row_index` + `column_index` |
| PDF 文本行 | `document_id` + `source_file` + `page_number` + `bbox` |

### 4.3 位置规则

1. **不得把 P1 的锚点列直接当作数值列。** 真实样本中 `column_index = 0` 指向指标名，数值在第 1 列。
2. **没有验证过的数值单元格不要填。** `value_row_index` / `value_column_index` 保持 `null` 或整个字段省略。
3. **Word 没有页码/坐标。** 不要为 Word 编造 `page_number` 或 `bbox`。
4. **`source_file` 必须指向真实文件。** 读取方应校验存在性；不存在时降级为人工核实。
5. **位置缺失是允许的，但必须人工核实。** `location = null` 时 `needs_manual_review` 必须为 `true`，读取方会自动补 `review_reasons = ["location_missing"]`。

## 5. 计算对象

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `formula` | `str \| null` | 否 | 公式 |
| `substituted_formula` | `str \| null` | 否 | 代入后的公式 |
| `operands` | `array` | 否 | 输入项 |
| `reported_value` | `number \| string \| null` | 否 | 文档原始计算值 |
| `computed_value` | `number \| null` | 否 | 正确值，仅验证后填写 |
| `unit` | `str \| null` | 否 | 结果单位 |
| `rounding` | `str \| null` | 否 | 舍入规则 |
| `tolerance` | `number \| null` | 否 | 允许误差 |
| `verification_status` | `str` | 否 | `not_attempted` / `verified` / `failed` / `error` |
| `verification_method` | `str \| null` | 否 | 验证方法 |
| `verification_detail` | `str \| null` | 否 | 验证过程 |
| `verified_at` | `str \| null` | 否 | UTC ISO |
| `notes` | `array[str]` | 否 | 补充说明 |
| `metadata` | `object` | 否 | 扩展信息 |

### 5.1 硬性规则

```text
computed_value 非空  =>  verification_status 必须为 "verified"
verification_status == "verified"  =>  computed_value 必须非空
```

违反任一规则，读取/构造直接报错，不允许静默接受。

`verification_status` 取值：

| 值 | 含义 |
| --- | --- |
| `not_attempted` | 未尝试计算 |
| `verified` | 计算已验证，`computed_value` 可信 |
| `failed` | 已计算但验证失败 |
| `error` | 计算过程出错 |

外部 AI 如果只给出可疑结论、没有可复现计算，应使用 `not_attempted` 并保持 `computed_value = null`，同时 `needs_manual_review = true`。

### 5.2 输入项对象

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | 是 | 名称 |
| `numeric_value` | `number \| null` | 否 | 计算用数值 |
| `raw_value` | `str \| null` | 否 | 原文表达 |
| `unit` | `str \| null` | 否 | 单位 |
| `source_location` | `object \| null` | 否 | 输入项位置，结构同位置对象 |
| `metadata` | `object` | 否 | 扩展信息 |

## 6. 仅有文字、无法定位的问题

```json
{
  "issue_id": "issue-0002",
  "issue_type": "text_inconsistency",
  "severity": "warning",
  "description": "正文与表格中的点位名称可能不一致。",
  "original_text": "监测点位：DW001 废水总排口",
  "location": null,
  "calculation": null,
  "needs_manual_review": true,
  "review_reasons": ["location_missing"],
  "suggestion": "请人工确认点位名称。",
  "status": "open",
  "metadata": {}
}
```

读取后会自动保持 `needs_manual_review = true`，并确保 `location_missing` 出现在 `review_reasons` 中。

## 7. 校验规则汇总

`ErrorList` 读取时执行：

1. 顶层必须是 JSON 对象；
2. `schema_version` 必须为 `"1.0"`；
3. `issues` 必须是数组；
4. 每个 `issue_id` 非空且批次内唯一；
5. 每个 `issue_type`、`description` 非空；
6. `severity`、`status`、`locator_method`、`verification_status` 必须在允许值内；
7. `locator_confidence` 在 0–1；
8. 位置对象中所有索引为整数或 `null`；
9. `bbox` 为 4 个数或 `null`；
10. 计算对象满足 5.1 的硬性规则；
11. 无位置的问题必须 `needs_manual_review = true`。

读取后，项目二还应额外校验：

- `document_id` 是否存在于当前 P1 批次；
- `source_file` 是否存在；
- Word 定位是否与 `file_type` 一致（不能给 Word 填 PDF 页码）；
- `table_index` / `row_index` / `column_index` 是否越界；
- `metadata.rows[row][column]` 是否包含 `original_text` 或可匹配片段；
- 数值单元格映射是否有表头依据。

这些跨批次校验不在 `ErrorList` 内部强制，因为错误清单本身不携带完整批次内容。

## 8. 与项目一 JSON 的关系

错误清单只引用项目一的位置，不复制整份批次：

- 项目一 JSON 是权威来源；
- 错误清单只保存 `document_id`、`source_file` 和索引；
- 外部 AI 不应把 Markdown 当作定位依据；
- Markdown 可用于人工阅读，但不能替代 JSON 的 Word 索引。

## 9. 输出到审核报告

`ErrorList.to_report(...)` 生成 `AuditReport`：

```text
ErrorList.issues
  -> AuditReport.issues
  -> AuditReport.summary()
  -> 下一阶段追加 AnnotationResult
```

批注结果 `AnnotationResult` 仍然通过 `issue_id` 关联回问题，不修改问题原始内容。
