# 错别字规则与识别说明

## 1. 目标

在现有环境数据审核流程中增加保守的中文错别字和明显文字错误检查。

原则：

- 只做有明确依据的判断。
- 不因为词语不常见就判定错误。
- 不自动替换原文。
- 高置信度问题可以自动批注；低置信度问题进入人工核实。
- 所有问题保留原文、建议修改、上下文、依据、规则编号和来源位置。

## 2. 扫描范围

Word：

- `paragraph` / `heading` 记录：段落级扫描。
- `table` 记录：逐单元格扫描 `metadata.cells` / `metadata.rows`。

PDF：

- `ocr_text` / `text_block` 记录：按 `page_number` 和 bbox 扫描。
- PDF 表格单元格：按 `cells[].bbox` 扫描。
- 如果表格有单元格 bbox，跳过表格内 OCR 文本，避免重复。
- 没有更细文本时才回退到 `ocr_page` / `page_text`。

## 3. 词典

词典位于 `src/word_audit/typo_rules.py`：

```python
TypoEntry(
    wrong="数剧",
    correct="数据",
    reason="同音字/常见错别字",
    confidence="high",
    rule_id="TYPO_001",
)
```

- `wrong`：错误写法
- `correct`：建议修改
- `reason`：判断依据
- `confidence`：`high` / `low`
- `rule_id`：可追踪规则编号

当前词典只包含人工确认条目，不做拼音自动纠错和编辑距离自动猜词。

## 4. 高置信度和低置信度

高置信度：

- `confidence = "high"`
- `needs_manual_review = false`
- `metadata.auto_annotate = true`
- 可以进入自动定位和批注流程。

低置信度：

- `confidence = "low"`
- `needs_manual_review = true`
- `metadata.auto_annotate = false`
- 只进入人工核实清单，不自动批注或标记。

## 5. 重复字规则

只对已知正确词做重复字检查：

- 末字重复：`企业业`、`数据据`、`监测测`
- 首字重复：`企企业`、`数数据`、`监监测`

正确词来源为 `REPEAT_GUARD_TERMS`。

不会使用任意连续重复字符规则，因此不会误报：

- `年年`
- `常常`
- `一一`

## 6. 保护规则

以下内容受保护，候选错误如果完全位于保护范围内则跳过：

- 项目一企业名称。
- 项目一环境指标、点位、单位。
- 内置环境专业词和污染物名称。
- 内置监测方法名称。
- 标准编号：
  - `GB 3838-2002`
  - `HJ 828-2017`
  - `DB44/T 1234-2020`
- 企业/机构名称模式：
  - 有限公司、有限责任公司、集团、研究院、检测中心、监测站、生态环境局等。
- 候选错误紧邻英文字母或数字时跳过。

## 7. 上下文和重复出现

每条问题记录：

- `original_text`：错误原文
- `suggestion`：建议修改
- `metadata.context`：第一个上下文片段
- `metadata.contexts`：同一位置所有上下文片段
- `metadata.occurrence_count`：同一段落/单元格/PDF 文本单元中出现次数
- `metadata.typo_reason`：判断依据
- `metadata.typo_rule_id`：规则编号
- `metadata.location_granularity`：定位粒度

同一单元多次出现相同错误只生成一条问题；不同段落/单元格/PDF 文本位置分别生成问题。

## 8. AuditIssue 映射

```text
issue_type = "typo"
severity = "warning"
original_text = 错误原文
suggestion = 建议修改
location = 项目一来源位置
calculation = null
needs_manual_review = confidence 为 low
```

`metadata`：

```text
audit_rule = "typo"
issue_type_label = "错别字"
typo_confidence
typo_rule_id
typo_reason
error_text
suggested_text
context
contexts
occurrence_count
auto_annotate
location_granularity
source_unit
synthetic（合成批次时）
```

## 9. PDF 定位粒度

- `pdf_text_line`：项目一只有整行 bbox，只能标记整行，不声称精确定位到单个汉字。
- `pdf_table_cell`：使用表格单元格 bbox。
- `pdf_unknown`：没有可用 bbox，进入人工核实，不自动标记。

## 10. 统计定义

完整报告 `metadata.pipeline.typo_counts`：

| 字段 | 定义 |
| --- | --- |
| `typo_issue_count` | 所有错别字问题数 |
| `typo_verified_count` | 高置信度错别字问题数 |
| `typo_manual_review_count` | 最终批注状态为 `skipped` 的错别字问题数 |
| `typo_annotation_success_count` | 错别字批注/标记成功数 |
| `typo_annotation_failed_count` | 错别字批注/标记失败数 |

`issues_flagged_for_manual_review` 和 `annotation_manual_review_count` 仍按原 pipeline 逻辑独立统计。

## 11. 当前限制

- 词典只覆盖人工确认的常见错误，不覆盖所有错别字。
- 不熟悉且不在保护词/企业名称/标准编号范围内的专有名词仍可能进入人工核实或被词典命中，需要人工确认。
- 不做拼音、OCR 相似度或编辑距离自动纠错。
- 漏字、多字只覆盖明确规则和人工词典，不做无依据补字。
- PDF 文本层或 bbox 不完整时只能人工核实。
- 不修改原始 Word/PDF。
