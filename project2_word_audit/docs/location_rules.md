# 错误位置定位规则

本阶段定位模块只读原始 Word / PDF 和项目一 JSON，不修改文件、不添加批注、不添加 PDF 标记。

## 1. 输入与输出

输入：

- 项目一 `batch.json`（`schema_version = "1.0"`）
- 项目二 `AuditIssue`，其中 `location` 为 `SourceLocation`

输出：

- `LocationResult`（`src/word_audit/models.py`）
- 定位逻辑在 `src/word_audit/location.py`

`LocationResult` 核心字段：

```text
issue_id, document_id, file_type,
page_number, paragraph_index, table_index, row_index, column_index,
bbox, matched_text, locator_confidence,
locator_status, needs_manual_review, failure_reason
```

## 2. 定位状态

| 状态 | 含义 | `needs_manual_review` |
| --- | --- | --- |
| `located` | 索引/坐标有效，且原文文本核对通过 | `false` |
| `ambiguous` | 文本在文档中出现多个候选，无法唯一确定 | `true` |
| `not_found` | 文档或目标位置不存在 | `true` |
| `invalid_location` | 索引越界、坐标无效、文件类型冲突等 | `true` |
| `manual_review` | 索引有效但文本不匹配、OCR 无文本、页面旋转等 | `true` |

代码强制：

- `located` 不得带 `needs_manual_review = true`；
- 非 `located` 必须 `needs_manual_review = true`；
- `located` 不得带 `failure_reason`。

即：不确定的位置不会被标成 `located`。

## 3. 文档解析

1. 通过 `AuditIssue.location.document_id` 在项目一批次中查找文档。
2. 文档不存在：`not_found`，原因 `document_not_found_in_batch`。
3. 使用项目一 `documents[].source_file` 作为权威文件路径，并校验文件存在。
4. `location.file_type` 与批次文档 `file_type` 不一致：`invalid_location`，原因 `file_type_mismatch`。
5. 只读打开文件；不保存、不写回。

## 4. Word 定位规则

### 4.1 段落

- 使用 `paragraph_index`，0 起。
- 索引按 Word 正文直接子段落顺序计算，与项目一 `word_parser.py` 的遍历方式一致。
- 只计算正文 `<w:p>`，表格不占用段落索引。
- 索引越界：`invalid_location`，原因 `paragraph_index_out_of_range`。

### 4.2 表格单元格

- 使用 `table_index`、`row_index`、`column_index`，均 0 起。
- `table_index` 按正文直接子表格顺序计算。
- 兼容项目一 Word 表格存放在 `records[].metadata.rows` 的实际结构；定位时读取真实 `.docx`。
- 表格、行、列越界分别返回 `invalid_location`：
  - `table_index_out_of_range`
  - `row_index_out_of_range`
  - `column_index_out_of_range`
- 缺少表格或行列索引：`invalid_location`，原因 `missing_word_index` / `incomplete_table_cell_index`。

### 4.3 锚点单元格与数值单元格

项目一环境记录的 `source_location.column_index` 通常指向指标单元格（例如 `"COD"` 在第 0 列），实际数值在第 1 列。

项目二 `SourceLocation` 中：

- `row_index` / `column_index`：项目一锚点；
- `value_row_index` / `value_column_index`：经验证的数值单元格。

Word 定位目标选择：

1. 若两个 value 索引都存在，优先定位数值单元格；
2. 否则定位锚点单元格；
3. 若数值单元格文本不匹配，但锚点单元格匹配，可回退到锚点单元格，置信度 0.8。

### 4.4 原文二次核对

文本归一化：

- Unicode NFKC；
- 去除所有空白字符；
- 大小写折叠。

匹配规则：

- `expected` 归一化后必须包含于 `actual` 归一化文本；
- 单元格文本匹配：置信度 0.95；
- 单元格不匹配但整行文本匹配：置信度 0.85；
- 数值单元格失败、锚点单元格匹配：置信度 0.8。

文本不匹配时：

- 在整份 Word 中搜索期望文本；
- 候选数 > 1：`ambiguous`，原因 `text_mismatch_multiple_candidates`；
- 候选数 0 或 1：`manual_review`，原因 `text_mismatch` 或 `text_mismatch_unique_candidate`；
- 不自动把唯一候选标记为 `located`，避免索引错位被掩盖。

### 4.5 同一单元格多个问题

每个 `AuditIssue` 独立定位，可产生多个 `LocationResult`，允许指向同一 `table_index/row_index/column_index`。

### 4.6 Word 限制

- Word 不提供 `page_number` 和 `bbox`，定位只到段落 / 表格 / 单元格。
- 不提供单元格内字符偏移；下一阶段批注需在单元格内再次匹配。
- 合并单元格在 `python-docx` 中可能重复文本；本阶段按实际读取结果处理。
- 文档移动导致 `source_file` 失效时返回 `not_found`。

## 5. PDF 定位规则

### 5.1 页码

- 使用项目一 `page_number`，1 起。
- 页码缺失：`invalid_location`，原因 `pdf_page_number_missing`。
- 页码越界：`invalid_location`，原因 `page_number_out_of_range`。

PDF **不使用 Word 的段落索引或表格索引作为定位依据**。`table_index` 只用于在项目一 PDF 表格数据中查找更精确的单元格 bbox。

### 5.2 坐标

- 项目一 PDF bbox 坐标空间为 PDF 点（`coordinate_space = "pdf"`）。
- 使用 PyMuPDF `page.rect` 获取页面尺寸。
- bbox 必须满足：
  - 恰好 4 个数；
  - `x1 > x0`、`y1 > y0`；
  - 在页面范围内，容差 1.0 pt。
- 若不满足：
  - `bbox_invalid`
  - `bbox_outside_page`
  - 状态为 `invalid_location`，`needs_manual_review = true`。

### 5.3 单元格 bbox 细化

若问题位置包含 `table_index` + `row_index/column_index`（或 value 行列），定位器会从项目一 PDF 表格 `cells[].bbox` 中查找对应单元格 bbox：

- 找到且有效：`bbox_source = "project1_cell"`；
- 找不到或无效：回退到 `location.bbox`，`bbox_source = "issue_location"`。

这可以在项目一只给出表格整体 bbox 时，细化到具体单元格。该过程仍只读项目一 JSON，不改变坐标空间。

### 5.4 坐标空间与页面旋转

- 若项目一表格 `coordinate_space` 存在且不是 `pdf`：`manual_review`，原因 `coordinate_space_not_pdf`。
- 若 `page.rotation != 0`：`manual_review`，原因 `page_rotation_not_supported`。
  - 当前版本不自动换算旋转后的坐标，避免把不确定位置标成 `located`。
- 缩放：项目一 bbox 应为 PDF 点，不是渲染图像像素；越界坐标会进入 `invalid_location`。

### 5.5 文本核对

1. 使用 `page.get_textbox(bbox)` 提取 bbox 内文本。
2. 若 bbox 内没有文本（扫描件 / OCR 层缺失）：`manual_review`，原因 `no_text_in_bbox`。
3. 若提取文本匹配 `original_text`：`located`。
   - 单元格 bbox：置信度 0.95；
   - 表格整体 bbox：置信度 0.9。
4. 若单元格文本不匹配，但项目一同一行文本匹配：`located`，置信度 0.85，记录 `match_scope = "row"`。
5. 若文本完全不匹配：
   - 期望文本在本页其他位置出现：`manual_review`，原因 `text_mismatch_found_on_page`；
   - 否则：`manual_review`，原因 `text_mismatch`。

### 5.6 PDF 限制

- PDF 的 OCR 识别误差会影响文本核对。
- 扫描 PDF 可能没有可提取文本，只能人工复核。
- 页面旋转、非 PDF 坐标空间暂不自动定位。
- 表格整体 bbox 无法精确到数字时，优先使用项目一单元格 bbox；若缺失则仍可能较宽。
- 不对 PDF 做任何标记或修改。

## 6. 置信度约定

| 场景 | 置信度 |
| --- | --- |
| Word 段落文本匹配 | 0.95 |
| Word 单元格文本匹配 | 0.95 |
| Word 整行文本匹配 | 0.85 |
| Word 回退到锚点单元格 | 0.80 |
| PDF 单元格 bbox + 单元格文本匹配 | 0.95 |
| PDF 表格整体 bbox + 文本匹配 | 0.90 |
| PDF 整行文本匹配 | 0.85 |
| 文本不匹配 / 歧义 / 人工复核 | 0.0–0.30 |
| 无效位置 / 未找到 | 0.0 |

这些是定位规则置信度，不是审核结论置信度。

## 7. 失败原因

```text
location_missing
document_not_found_in_batch
file_type_mismatch
unsupported_file_type
word_file_not_found
pdf_file_not_found

paragraph_index_out_of_range
table_index_out_of_range
row_index_out_of_range
column_index_out_of_range
missing_word_index
incomplete_table_cell_index

pdf_page_number_missing
page_number_out_of_range
bbox_invalid
bbox_outside_page
coordinate_space_not_pdf
page_rotation_not_supported

no_expected_text
no_text_in_bbox
text_mismatch
text_mismatch_multiple_candidates
text_mismatch_unique_candidate
text_mismatch_found_on_page
```

## 8. 只读性

- Word 使用 `python-docx` 读取，不调用 `save()`。
- PDF 使用 PyMuPDF 只读打开，不写回。
- 项目一 `batch.json` 只读。
- 测试在定位前后计算批次 JSON、Word、PDF 的 SHA-256，要求一致。
