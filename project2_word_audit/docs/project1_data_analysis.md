# 项目一数据接口分析

## 1. 分析对象与方法

本分析只读取项目一现有代码、README 和真实批次 JSON，不修改项目一。

| 对象 | 路径 |
| --- | --- |
| 项目一 README | `D:\DocumentAuditSystem\project1_extraction\README.md` |
| 核心模型 | `src/doc_extractor/core/models.py`、`table_models.py`、`environmental_models.py` |
| Word 解析 | `src/doc_extractor/core/word_parser.py` |
| JSON 导出 | `src/doc_extractor/core/exporters.py`、`batch_io.py`、`extraction_batch.py` |
| 真实批次 | `output/batches/20261101T053459830362Z_0e022780/batch.json` |

真实批次大小约 121 KB，`schema_version = "1.0"`，包含 2 份文档（1 个 Word、1 个 PDF）、1 个 PDF 表格、9 条环境记录。所有环境记录均处于 `pending_review`。

为验证能否关联回原始 Word，另外用 Python 标准库 `zipfile` + `xml.etree` 直接读取了 `01_企业废水监测报告.docx` 的 `word/document.xml`，与 JSON 内容逐项比对。未使用项目一代码重新解析。

## 2. 批次 JSON 顶层结构

实际顶层字段：

```text
schema_version, batch_id, extracted_at, exported_at,
document_count, table_count, documents, tables, environmental
```

实际值：

| 字段 | 实际值 | 说明 |
| --- | --- | --- |
| `schema_version` | `"1.0"` | 当前唯一结构版本 |
| `batch_id` | `"20261101T053459830362Z_0e022780"` | 批次唯一 ID |
| `extracted_at` | `"2026-11-01T05:34:59.830362+00:00"` | UTC |
| `exported_at` | `"2026-11-01T05:34:59.833865+00:00"` | UTC |
| `document_count` | `2` | Word + PDF |
| `table_count` | `1` | **只统计 `documents[].tables`，Word 表格不计入** |
| `documents` | 2 项 | 每份文档的解析结果 |
| `tables` | 1 项 | 所有 `DocumentResult.tables` 的汇总，**同样不含 Word 表格** |
| `environmental` | 对象 | 企业归并 + 环境记录 |

重要限制：`table_count` 和顶层 `tables` 不能作为“文档中全部表格”的依据。Word 表格必须从 `documents[].records[]` 中 `content_type = "table"` 的记录读取。

## 3. 文档层字段

`documents[]` 实际字段：

```text
document_id, source_name, source_file, file_type,
record_count, table_count, records, tables,
warnings, error, metadata
```

### 3.1 Word 文档

实际值：

| 字段 | 实际值 |
| --- | --- |
| `document_id` | `19353a83da7e47c1b236f87ff7036c71` |
| `source_name` | `01_企业废水监测报告.docx` |
| `source_file` | `D:\DocumentAuditSystem\project1_extraction\test_data\01_企业废水监测报告.docx`（绝对路径） |
| `file_type` | `"word"` |
| `record_count` | `6` |
| `table_count` | `0` |
| `tables` | `[]` |
| `metadata` | `{"paragraph_count": 5, "table_count": 1, "content_block_count": 6}` |

矛盾点：Word 的 `document.table_count = 0`，但 `document.metadata.table_count = 1`，且 `records` 中确有 1 条表格记录。读取方不能只看 `document.table_count`。

Word 记录类型统计：

```text
heading: 1, paragraph: 4, table: 1
```

Word 记录位置：

- 标题/段落：`paragraph_index` 为 0、1、2、3、4，`table_index/page_number/bbox/block_index/reading_order` 全为 `null`。
- 表格记录：`table_index = 0`，`paragraph_index/page_number/bbox` 全为 `null`。

Word 的 `metadata` 中没有 `extraction_engine`、`extraction_mode`，也没有页码信息。

### 3.2 PDF 文档

实际值：

| 字段 | 实际值 |
| --- | --- |
| `document_id` | `7ee840b30f3f492aadf8ab61ff0fa276` |
| `source_name` | `02_企业废气监测报告.pdf` |
| `file_type` | `"pdf"` |
| `record_count` | `26` |
| `table_count` | `1` |
| `tables` | 1 项统一表格 |
| `metadata` | 含 `page_count=1`、`extraction_engine="PaddleOCR"`、`extraction_mode="local_gpu"`、`ocr_used=true`、`dpi=200`、`local_device`、`coordinate_transform` 相关信息 |

PDF 记录类型统计：

```text
ocr_page: 1, ocr_text: 24, table: 1
```

PDF 表格内容同时出现在三类位置：

1. `documents[].records[]` 中的 `table` 记录；
2. `documents[].tables[]` 中的统一表格；
3. 顶层 `tables[]` 中的同一张表。

此外，表格范围内的文字还被 OCR 逐行输出为 `ocr_text` 记录（例如“监测项目”“8.6”“mg/m”）。审计时如果同时使用 OCR 文本和表格记录，必须去重，否则会重复审核同一数值。

## 4. 记录层字段与来源位置

### 4.1 通用记录

每条 `records[]`：

```text
document_id, source_file, file_type, content_type, text, location, metadata
```

`location` 固定包含：

```text
paragraph_index, table_index, row_index, column_index,
page_number, bbox, block_index, reading_order
```

实际语义：

| 内容 | 可用定位 |
| --- | --- |
| Word 段落 | `paragraph_index`（从 0 开始，正文段落顺序） |
| Word 表格 | `table_index`（从 0 开始，本文档表格顺序） |
| Word 表格单元格 | 记录层 `location` 仍是 `row_index = null, column_index = null`；行列索引在 `metadata.cells[]` 和 `environmental.records[].source_location` 中 |
| PDF 文本 | `page_number` + `bbox`，部分有 `reading_order`；`paragraph_index = null` |
| PDF 表格 | `page_number` + `bbox` + `table_index`；单元格在 `metadata.cells[]` |

### 4.2 Word 表格是否存储在 `records[].metadata.rows`

**确认：是。**

真实 Word 表格记录：

```json
{
  "content_type": "table",
  "location": {"table_index": 0, "paragraph_index": null, "page_number": null},
  "metadata": {
    "row_count": 6,
    "column_count": 4,
    "rows": [
      ["监测项目", "监测结果", "单位", "检测方法/备注"],
      ["COD", "85", "mg/L", "模拟检测"],
      ["氨氮", "12.5", "mg/L", "模拟检测"],
      ["总磷", "<0.01", "mg/L", "低于报告限"],
      ["总氮", "18.2", "mg/L", "模拟检测"],
      ["pH", "7.3", "无量纲", "模拟检测"]
    ],
    "cells": [
      {"row_index": 0, "column_index": 0, "text": "监测项目", "entities": []},
      {"row_index": 1, "column_index": 1, "text": "85", "entities": [
        {"type": "integer", "text": "85", "start": 0, "end": 2, "value": 85}
      ]}
    ]
  }
}
```

Word 表格记录 `metadata` 实际键：

```text
document_order, row_count, column_count, rows, cells, source, entities
```

**缺少**：`headers`、`header_row_count`、`table_id`、`needs_review`、`review_reasons`、`extraction_engine`、`coordinate_transform`、`bbox`。

Word `cells[]` 只有：

```text
row_index, column_index, text, entities
```

没有 `bbox`、`row_span`、`column_span`、`confidence`、`is_header`。因此：
- 无法从 Word JSON 得到单元格坐标；
- 无法直接得到合并单元格跨度；
- 表头行需要项目二自行推断，不能假设 P1 已给出。

### 4.3 PDF 表格

PDF 表格记录 `metadata` 实际键：

```text
source, extraction_engine, extraction_mode, page_table_index,
row_count, column_count, rows, cells, entities,
table_id, headers, header_row_count, needs_review, review_reasons,
coordinate_transform, unified_table
```

PDF `cells[]` 含：

```text
row_index, column_index, text, bbox, image_bbox,
row_span, column_span, confidence, is_header, entities
```

顶层统一表格（`tables[]` / `documents[].tables[]`）字段：

```text
source_file, page_number, table_id, table_bbox, extraction_engine,
rows, columns, headers, header_row_count, cells, needs_review,
review_reasons, confidence, coordinate_space, image_table_bbox,
image_size, pdf_size, coordinate_transform, metadata
```

真实值示例：`table_id = "p1-t0"`，`table_bbox = [61.552, 180.351, 531.649, 341.264]`，`coordinate_space = "pdf"`，`confidence = 0.9985`。

### 4.4 实体偏移

- 单元格 `entities[]` 的 `start/end` 相对于**该单元格文本**。例如单元格 `"85"` 的实体偏移为 0–2。
- 表格记录 `metadata.entities[]` 的 `start/end` 相对于**整张表用 `\t`/换行拼接后的文本**。例如 `"85"` 在整表文本中的偏移为 25–27。

项目二如需字符级定位，必须明确使用哪一层偏移，不能混用。

## 5. 环境记录结构

`environmental.records[]` 实际字段（共 31 个）：

```text
record_id, category, category_label, subcategory, subcategory_label,
enterprise_id, enterprise_name, unified_social_credit_code,
document_id, source_file, file_type,
indicator, value, unit, time, point, detection_limit,
source_location, source_content_type, source_text, raw_expression,
extraction_engine, extraction_mode,
flags, flag_labels, status, status_label, needs_review,
confidence, metadata
```

真实样本统计：

| 项目 | 值 |
| --- | --- |
| 环境记录数 | 9 |
| 待核实数 | 9 |
| 企业数 | 1（`identity_status = "name_only"`） |
| 分类 | 环境监测 9 条；环保管理 0 条；环境统计 0 条 |
| Word 记录 | 5 条废水数据，`table_index = 0`，`row_index` 1–5，`column_index = 0` |
| PDF 记录 | 4 条废气数据，`table_index = 0`，`row_index` 1–4，`column_index = 0`，`page_number = 1` |

### 5.1 关键发现：`source_location` 指向指标单元格，不是数值单元格

Word 实际记录：

```json
{
  "indicator": "COD",
  "value": 85,
  "unit": "mg/L",
  "source_location": {
    "paragraph_index": null,
    "table_index": 0,
    "row_index": 1,
    "column_index": 0,
    "page_number": null,
    "bbox": null
  },
  "source_text": "COD\t85\tmg/L\t模拟检测"
}
```

该行 `rows[1] = ["COD", "85", "mg/L", "模拟检测"]`：`column_index = 0` 指向 `"COD"`，数值 `85` 在 `column_index = 1`。PDF 记录同样如此（颗粒物行：`column_index = 0`，数值 `8.6` 在第 1 列）。

原因：P1 的表格行级来源单元按“指标文本匹配位置”确定列索引，未单独记录“数值所在单元格”。P1 代码中的列级表格提取路径仅在表头本身就是指标名时生效，本样本表头是“监测项目/监测结果/单位”，因此走行级路径。

结论：**不能直接把 `source_location.column_index` 当作数值单元格列索引**。项目二必须增加“锚点单元格”和“数值单元格”的区分，或根据表头映射后重新计算，并标注定位置信度。

### 5.2 单位与原文差异

真实 PDF 记录：

- `source_text = "颗粒物\t8.6\tmg/m\t模拟检测"`
- `raw_expression = "颗粒物\t8.6\tmg/m\t模拟检测"`
- `unit = "mg/m³"`

即 P1 对 `unit` 做了规范化，而 `source_text` / `raw_expression` 保留原始表达。审计比对时应明确使用规范化单位还是原文单位。

检出限样本：

- Word 总磷：`value = null`，`detection_limit = "<0.01"`，`source_text = "总磷\t<0.01\tmg/L\t低于报告限"`
- PDF 二氧化硫：`value = null`，`detection_limit = "ND"`

P1 不会把检出限换算为 0，项目二也必须保持这一规则。

### 5.3 其他字段语义

- `confidence` 是 P1 规则识别置信度（本样本 0.7–0.8），不是定位置信度，也不是审计结论置信度。
- `metadata` 中包含 `table_index`、`row_index`、`column_index`、`source_unit_type`、`time_from_document_context`、`point_from_document_context`、企业身份状态等。
- Word 记录的 `extraction_engine` 为 `"PaddleOCR"`，但这批 Word 实际由 `python-docx` 解析；该值是模型默认值。`extraction_mode` 为 `null`。不能据此判断 Word 使用了 OCR。
- `flags` 本样本全部含 `enterprise_identity_unverified`；总磷、二氧化硫额外含 `detection_limit`。

## 6. 能否关联回原始 Word

**能，但只能到“段落 / 表格 / 单元格”级别，不能到页码、坐标或字符 run 级别。**

### 6.1 已实际验证的关联

对 `01_企业废水监测报告.docx` 直接解析 `word/document.xml`：

| 比对项 | JSON | Word 文件 | 结果 |
| --- | --- | --- | --- |
| `source_file` 是否存在 | 绝对路径 | 文件存在，37,248 字节 | 通过 |
| `metadata.paragraph_count` | 5 | 正文 `<w:p>` 5 个 | 一致 |
| `metadata.table_count` | 1 | 正文 `<w:tbl>` 1 个 | 一致 |
| 段落索引 0–4 文本 | 5 条 | 5 段文本 | 逐条完全一致 |
| 表格索引 0 的行列内容 | 6 行 × 4 列 | 6 行 × 4 列 | 完全一致 |

因此可用的 Word 关联链为：

```text
batch_id
  -> document_id
  -> source_file（绝对路径，需校验存在）
  -> paragraph_index（正文段落序号，0 起）
     或 table_index + row_index + column_index（表格/单元格，0 起）
```

### 6.2 索引语义与边界

- `paragraph_index` 是正文直接子段落的序号，从 0 开始；空段落也会消耗索引，但没有对应记录。
- `table_index` 是正文直接子表格的序号，从 0 开始，按文档内顺序编号。
- `row_index` / `column_index` 从 0 开始，对应 `rows` 二维数组中的位置。
- `document_order` 是正文块顺序（段落和表格统一计数），保存在记录 `metadata.document_order`，不在 `location` 中。
- 表格单元格没有 run 级或字符级索引，无法直接定位到单元格内某一个数字的字符范围；需要项目二在单元格文本内再次匹配。

### 6.3 定位能力矩阵

| 目标 | 可用字段 | 置信度判断 | 限制 |
| --- | --- | --- | --- |
| Word 段落 | `document_id` + `source_file` + `paragraph_index` | 高（索引已实测一致） | 无页码/坐标；空段落索引有空洞 |
| Word 表格整体 | `document_id` + `source_file` + `table_index` | 高 | 无 bbox |
| Word 单元格（锚点） | 再加 `row_index` + `column_index`，文本在 `metadata.rows` / `cells` | 高，但需核对单元格文本 | 合并单元格可能重复文本；无跨度字段 |
| Word 数值单元格 | P1 未直接给出 | 中，需要按表头映射并核对 | 不能把锚点列当数值列 |
| PDF 表格单元格 | `page_number` + `table_index` + `row_index` + `column_index` + `cells[].bbox` | 高 | 依赖 OCR 表格结构 |
| PDF 文本行 | `page_number` + `bbox` + `reading_order` | 中高 | 无段落索引 |
| Word 页码 | 无 | 不可用 | `page_number` 全为 `null` |
| Word 坐标 | 无 | 不可用 | `bbox` 全为 `null` |

## 7. 数据交换结论

1. **项目一 JSON 批次是主要输入。** 其正式路径约定为 `output/batches/<batch_id>/batch.json`，`schema_version = "1.0"`。
2. **Markdown 只作辅助输入。** 项目一 README 明确 Markdown 用于人工阅读，不作为主要交换格式。项目二的设计不依赖 Markdown 提供 Word 定位信息。
3. **外部 AI 审核结果使用 JSON。** 项目二定义统一错误清单 JSON，再由项目二校验定位并生成审核报告与批注结果。
4. **不假设 Markdown 能提供完整定位。** Word 定位以 JSON 的 `document_id`、`source_file`、`paragraph_index`、`table_index`、`row_index`、`column_index` 为准。
5. **不假设 P1 已给出正确计算值。** P1 README 明确“不进行单位换算、数值计算”，因此正确计算值只能由项目二在可复现计算验证后填写。

## 8. 已知限制清单

1. Word 记录无 `page_number`、无 `bbox`，不能按页或坐标批注。
2. Word 表格不在 `document.tables` / 顶层 `tables` 中，且 `document.table_count = 0` 与 `metadata.table_count = 1` 不一致。
3. Word 表格记录无 `headers`、`header_row_count`，表头行需项目二自行推断。
4. Word 表格单元格无 `bbox`、`row_span`、`column_span`、`confidence`。代码层面 `python-docx` 的 `row.cells` 会重复合并单元格文本，本样本未包含合并单元格，未做实测验证。
5. `environmental.records[].source_location` 的 `row_index`/`column_index` 指向指标单元格；本样本 `column_index` 均为 0，数值实际在第 1 列。
6. 环境记录的 `confidence` 是规则识别置信度，不能当定位置信度或审计置信度。
7. 单位可能被规范化（`mg/m` -> `mg/m³`），原文保留在 `source_text` / `raw_expression`。
8. `source_file` 为绝对路径，文件移动或跨机器后会失效，使用前必须校验存在性。
9. PDF 表格文字同时出现在 `ocr_text` 与 `table` 记录中，审计上下文需要去重。
10. Word 的 `extraction_engine = "PaddleOCR"` 是默认值，不代表 Word 经过 OCR；`extraction_mode = null`。
11. 记录只提供单元格级定位，不提供单元格内字符偏移；表格级 `entities` 与单元格级 `entities` 的偏移基准不同。
12. P1 明确不做计算、单位换算和合规判断，项目二不得把 P1 的 `value` 当作“正确计算值”。
