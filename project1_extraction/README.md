# 综合环境数据提取系统（project1_extraction）

面向企业环境数据智能审核系统的“综合环境数据提取模块”，是文档智能审核软件的第一个独立子项目。

系统在原有 Word/PDF 通用解析基础上，新增环境监测、环保管理、环境统计三类业务识别，支持一个企业导入多份 Word/PDF 文件并关联到同一企业，所有提取结果保留原始文件、页面/段落/表格/坐标等来源信息。

本阶段只实现数据提取，不包含自动计算、合规判断、AI 审核或 Word 批注。

除桌面界面外，现已提供无界面 Python API、固定目录批次输出和 CLI 命令行接口，便于项目二直接消费标准化 JSON 数据。

## 功能概览

### 通用文档解析

- Word（`.docx`）：正文、标题、表格、段落/表格/行列索引。
- PDF：统一使用 PaddleOCR PP-StructureV3，支持本地与云端两种模式。
- `local_gpu`：本地 PaddleOCR 推理模式标签。实际运行设备由 Paddle 决定；当前环境为 PaddlePaddle CPU 版，无 CUDA 设备，实际设备为 CPU，程序会明确记录并提示。
- `cloud_api`：PaddleOCR 官方云端 API，模型固定为 PP-StructureV3；提取前会提示并确认 PDF 上传。
- 普通电子 PDF、扫描 PDF、混合型 PDF 均走相同的统一解析接口。
- PyMuPDF 仅用于 PDF 页面图像渲染/页面尺寸读取，不参与文字提取或表格识别。
- RapidOCR 已停用，PDF 解析失败时不会静默切换引擎，也不会自动切换本地/云端模式。
- 两种模式输出相同的环境数据、表格数据、来源页码/坐标、待核实标记与 JSON/Excel 结构。
- 数字、小数、金额、百分比、日期识别。
- 输出统一通用记录模型与统一表格数据模型，支持 JSON 序列化。

### 统一表格数据模型

不同引擎的表格输出统一转换为：

- `source_file`、`page_number`、`table_id`、`table_bbox`
- `extraction_engine`（固定为 `PaddleOCR PP-StructureV3`）
- `rows`、`columns`、`headers`、`header_row_count`
- `cells`：`row_index`、`column_index`、`text`、`bbox`、`row_span`、`column_span`、`confidence`
- `needs_review`、`review_reasons`、`confidence`
- `image_bbox`、`image_size`、`pdf_size`、`coordinate_transform`

无法确定的字段保留为 `null`；同时保留图像像素坐标与 PDF 坐标的转换关系。

### 三类环境业务提取

三个相互独立的业务模块：

- `environmental_monitoring_extractor`：环境监测（废水、废气、噪声）。
- `environmental_management_extractor`：环保管理（排污许可证、管理台账、治理设施运行记录）。
- `environmental_statistics_extractor`：环境统计（用水量、能源消耗、污染物产生/排放量）。

基础版本采用规则识别，覆盖常见指标、单位、日期、点位、检出限表达。指标字典可继续扩展。

### 企业归并与身份核验

- 优先按统一社会信用代码归并多份文件。
- 无统一社会信用代码时，仅按完全一致的企业名称归并，并标记“企业身份未完全核验”。
- 企业身份不明确（无名称/代码、多个名称或多个代码）时按独立企业处理，不自动合并。
- 不做模糊匹配、不做猜测性合并。

### 人工核实标记

对以下情况生成 `pending_review` 记录并写入 `flags`，不自行补全：

- 缺少单位 `missing_unit`
- 缺少数值 `missing_value`
- 数值存在歧义 `ambiguous_value`
- 检出限表达 `detection_limit`
- 缺少时间 `missing_time`
- 缺少点位 `missing_point`
- 企业身份不明确/未完全核验
- 无法识别、低置信度

检出限表达（如 `未检出`、`<0.01 mg/L`）保留原始表达，`value` 保持空值，不换算为 0。

### 桌面界面

- 导入 Word / 导入 PDF / 批量导入。
- 后台线程执行通用解析与环境业务提取，界面不卡死。
- 原有标签页：原始文字、结构化信息、表格数据、实体识别。
- 新增“环境数据”标签页，内含环境监测、环保管理、环境统计三个子标签。
- 文件列表显示企业归并结果。
- 环境数据支持按企业筛选，显示指标、数值、单位、时间、点位、检出限、来源和核实状态。
- 显示完整来源位置与原始表达。
- 导出 JSON / Excel，包含通用记录、环境数据、企业分组和来源信息。

### 无界面 API 与命令行

- Python API：不启动 GUI，直接调用 Word/PDF 提取、批次保存、批次恢复和格式导出。
- CLI：支持 `extract`、`export` 子命令，可脚本化批量处理。
- 固定输出目录：`output/json`、`output/excel`、`output/markdown`、`output/batches`。
- 批次自动生成唯一 `batch_id`，重复保存或重复导出不会覆盖已有文件。
- 批次 JSON 支持导出的同时重新导入，恢复 `DocumentResult` 和 `EnvironmentalExtractionResult`。
- Markdown 仅用于人工阅读，不作为主要数据交换格式。

## 环境要求

- Windows 10/11 x64
- Python 3.12（推荐 3.12.10）
- 项目级虚拟环境 `.venv`
- PaddleOCR 3.x + PaddlePaddle 3.x（PDF 解析必需）
- PaddleOCR 云端 API 客户端已包含在 PaddleOCR 3.7.0 中（`requests`）

当前验证版本：PaddleOCR 3.7.0、PaddlePaddle 3.3.1、PyMuPDF 2.0、PySide6 6.12.0。
当前机器 Paddle 为 **CPU 版**，无 CUDA 设备；`local_gpu` 只是模式标签，实际 Paddle 设备为 `cpu`，界面会明确显示 GPU 不可用。

PDF 的 PP-StructureV3 初始化参数包含 `enable_mkldnn=False`，用于规避 PaddlePaddle 3.3.1 CPU/PIR 路径上的
`ConvertPirAttribute2RuntimeAttribute not support` 错误。该设置会降低 CPU 推理速度，但已通过真实样本和完整回归测试，
详见 `docs/PaddleOCR_PDF兼容性修复报告.md`。

## 安装

```powershell
# 1. 进入项目根目录
cd <仓库根目录>/project1_extraction

# 2. 同步运行依赖（uv 会根据 .python-version 使用 Python 3.12）
uv sync

# 3. 开发/测试时额外安装 pytest
uv sync --extra dev

# PaddleOCR / PaddlePaddle / requests 已包含在主依赖中
# PDF 解析支持 local_gpu 与 cloud_api 两种模式
```

`requirements.txt` 仅作为兼容文件保留，不再是主要安装方式。依赖版本以
`pyproject.toml` 和 `uv.lock` 为准。

首次运行 PP-StructureV3 会自动下载模型。Windows 用户名包含中文时，Paddle
原生推理无法打开含中文的模型路径，程序会自动将模型缓存指向项目下
`.paddlex_cache/`（ASCII 路径）；也可手动设置：

```powershell
$env:PADDLE_PDX_CACHE_HOME = "<ASCII 缓存目录>"
```

### 云端 API Token 安全配置

云端模式从环境变量 `PADDLEOCR_ACCESS_TOKEN` 读取 Token，不硬编码、不显示、不写日志、不提交到 Git。

当前 PowerShell 会话设置只对当前进程有效：

```powershell
$env:PADDLEOCR_ACCESS_TOKEN = "你的 Token"
uv run python -m doc_extractor
```

需要让以后启动的软件也能读取时，使用 Windows 用户环境变量（不要写入项目文件）：

```powershell
setx PADDLEOCR_ACCESS_TOKEN "你的 Token"
```

设置后重新打开终端/软件。程序界面只显示“Token 已配置/未配置”，不会显示 Token 内容。

若 PowerShell 阻止激活脚本：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

## 启动

```powershell
uv run python -m doc_extractor
```

或：

```powershell
uv run doc-extractor
```

无界面冒烟验证：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run python -m doc_extractor --smoke-test
```

## 命令行使用

命令行入口为项目根目录 `main.py`，不依赖 GUI。

```powershell
# 查看帮助
uv run python main.py --help

# 提取单个 Word
uv run python main.py extract --input "test_data\01_企业废水监测报告.docx"

# 提取单个 PDF
uv run python main.py extract --input "test_data\02_企业废气监测报告.pdf"

# 多文件批量提取，并额外保存 Markdown 和 Excel
uv run python main.py extract `
  --input "test_data\01_企业废水监测报告.docx" `
  --input "test_data\02_企业废气监测报告.pdf" `
  --save-format json --save-format markdown --save-format excel

# 导出最新批次的 JSON / Markdown / Excel
uv run python main.py export --format json
uv run python main.py export --format markdown
uv run python main.py export --format excel

# 指定批次导出
uv run python main.py export --format markdown --batch-id <batch_id>

# 从任意批次 JSON 文件导出，并指定输出路径
uv run python main.py export `
  --format json `
  --batch-file "output\batches\<batch_id>\batch.json" `
  --output "output\json\restored.json"
```

说明：

- `extract` 默认保存批次文件和 JSON；可通过 `--save-format` 追加 Markdown、Excel。
- `extract` 在标准输出打印批次 ID，后续 `export` 可使用该 ID。
- `export` 省略 `--batch-id` / `--batch-file` 时使用最新批次。
- `--output-root` 可指定其他输出根目录。
- `--mode` 支持 `local_gpu` 和 `cloud_api`，默认 `local_gpu`。
- 高级可选参数：`--dpi`（默认 200）、`--request-timeout`、`--poll-timeout`（云端 API 超时）。
- `export` 支持 `--format`、`--batch-id`、`--batch-file`、`--output-root`、`--output`。
- 原有 GUI 启动方式保持不变：`python -m doc_extractor` 或 `doc-extractor.exe` 仍启动桌面界面。

## 无界面 Python API

```python
from doc_extractor.api import (
    extract_file,
    extract_files,
    extract_and_save,
    save_batch,
    load_batch,
    load_latest_batch,
    export_batch,
)

# 提取单个文件，返回 ExtractionBatch
batch = extract_file("test_data/01_企业废水监测报告.docx")

# 批量提取并保存到固定输出目录
batch, outputs = extract_and_save(
    ["test_data/01_企业废水监测报告.docx", "test_data/02_企业废气监测报告.pdf"],
    formats=("json", "markdown", "excel"),
)
print(batch.batch_id)
print(outputs["json"])
print(outputs["markdown"])
print(outputs["excel"])

# 保存批次到指定输出根目录
saved = save_batch(batch, "output", formats=("json",))

# 从批次 JSON 恢复
restored = load_batch(saved["batch"])
latest = load_latest_batch("output")

# 重新导出
export_batch(restored, "markdown", "output")
```

`ExtractionBatch` 是统一返回结构：

- `batch_id`：批次唯一 ID。
- `extracted_at`：UTC 提取时间。
- `documents`：每份 Word/PDF 的 `DocumentResult` 列表。
- `environmental`：企业归并和环境数据结果。

## 固定输出目录

```text
output/
├── json/
├── excel/
├── markdown/
└── batches/
    └── <batch_id>/
        └── batch.json
```

- 每批次生成唯一 `batch_id`，文件名默认使用 `batch_id`。
- 保存或导出时如果目标文件已存在，会自动追加 `_1`、`_2` 等后缀，不覆盖已有结果。
- 默认输出根目录为项目根目录下的 `output/`。
- 可通过环境变量 `DOC_EXTRACTOR_OUTPUT_DIR` 或参数 `--output-root` 覆盖。
- `output/batches/<batch_id>/batch.json` 是用于批次恢复的权威 JSON。
- 原始 Word/PDF 文件只读，导出逻辑会阻止覆盖原始文件。

## 使用流程

1. 导入一个或多个 Word/PDF 文件。
2. 选择解析模式：
   - `本地 GPU（PaddleOCR）`：本地 PaddleOCR；GPU 不可用时界面提示并继续使用 CPU，不自动切云端。
   - `云端 API（PaddleOCR）`：使用 PaddleOCR 官方云端 PP-StructureV3；PDF 会上传，开始提取前需要确认。
3. 点击“开始提取”。
4. 在文件列表查看企业归并结果与通用记录数。
5. 切换到“PDF 原页”查看原始页面，红框标出识别到的表格区域。
6. 切换到“表格数据”查看表格结构、单元格、识别引擎/模式与待核实原因。
7. 切换到“环境数据”，按环境监测、环保管理、环境统计查看结果。
8. 使用“企业筛选”查看某一企业的全部文件数据。
9. 选中记录查看完整 JSON 来源信息、提取模式和核实标记。
10. 导出 JSON/Excel。

## 统一环境数据模型

环境记录主要字段：

| 字段 | 说明 |
| --- | --- |
| `record_id` | 环境记录唯一 ID |
| `category` | 环境监测/环保管理/环境统计 |
| `subcategory` | 废水、废气、噪声、排污许可、台账、设施运行、水、能源、污染物等 |
| `enterprise_id` / `enterprise_name` | 企业归并 ID 与名称 |
| `unified_social_credit_code` | 统一社会信用代码 |
| `document_id` / `source_file` / `file_type` | 来源文档 |
| `indicator` | 指标 |
| `value` | 数值或文本值（未识别时不补全） |
| `unit` | 单位（缺失时为空并标记） |
| `time` | 日期或统计期间 |
| `point` | 监测点位/排放口 |
| `detection_limit` | 检出限原始表达 |
| `source_location` | 段落/表格/行列/页码/坐标 |
| `source_content_type` | 段落、文本块、表格、OCR 等 |
| `source_text` / `raw_expression` | 来源全文与原始表达 |
| `extraction_engine` | 固定为 `PaddleOCR` |
| `extraction_mode` | `local_gpu` 或 `cloud_api` |
| `flags` / `status` | 核实标记与状态 |
| `confidence` | 规则识别置信度 |
| `metadata` | 指标别名、企业身份状态等扩展信息 |

`status` 取值：

- `complete`：已识别且未触发核实标记。
- `pending_review`：存在缺失、歧义、检出限、企业身份未核验等情况，等待人工核实。

## 企业归并规则

- 统一社会信用代码完全一致：归并为同一企业（`verified`）。
- 无代码但企业名称完全一致：可归并，标记 `name_only`。
- 名称一致且能匹配到已有代码企业：归并，标记 `name_matched`，提示人工核实。
- 无企业名称/代码、多个名称或多个代码：按独立企业处理，标记 `unclear`。
- 不进行模糊名称匹配或猜测性合并。

## 导出格式

### JSON

JSON 是项目一与项目二之间的主要数据交换格式，当前结构版本为 `schema_version = "1.0"`。

顶层包含：

- `schema_version`：数据结构版本号。
- `batch_id`：批次唯一 ID。
- `extracted_at`：UTC 提取时间。
- `exported_at`：UTC 导出时间。
- `document_count` / `table_count`：文档与表格数量。
- `documents`：通用文档解析记录。
  - `document_id`
  - `source_name`：原始文件名称。
  - `source_file`：原始文件路径。
  - `file_type`：`word` / `pdf`。
  - `records`：提取文本、内容类型、来源位置、元数据。
  - `tables`：该文档的统一表格数据。
  - `warnings` / `error` / `metadata`
- `tables`：全部文档的统一表格数据模型。
- `environmental`：环境数据结果。
  - `enterprises`
  - `records`
  - `warnings`
  - 分类统计

通用记录的来源位置字段：

- `paragraph_index`：段落索引。
- `table_index`：表格索引。
- `row_index` / `column_index`：行列位置。
- `page_number`：页码。
- `bbox`：页面坐标。
- `block_index` / `reading_order`：文本块与阅读顺序。

表格记录和统一表格模型的单元格包含原文内容、行/列索引、跨度、置信度、bbox 和来源信息。

JSON 导入与批次恢复：

```python
from doc_extractor.api import load_batch, load_latest_batch

batch = load_batch("output/batches/<batch_id>/batch.json")
latest = load_latest_batch("output")
```

也可以直接导入手工导出的 JSON：

```python
batch = load_batch("output/json/<batch_id>.json")
```

### Markdown

Markdown 用于人工阅读和快速核对，不作为主要数据交换格式。

- 支持 Word/PDF 提取结果。
- 展示文件名、文件路径、文件类型、记录数和表格数。
- 展示段落、OCR 文本和表格。
- 每个段落/表格保留来源位置。
- 展示企业汇总、环境数据记录、核实状态和原始表达。

### Excel

工作表：

- `文件汇总`
- `记录`
- `表格数据`
- `实体信息`
- `环境数据`
- `企业汇总`

`环境数据` 工作表包含企业、类别、指标、数值、单位、时间、点位、检出限、状态、标记、来源位置、原始表达、源文本等完整来源信息。

## 项目结构

```text
project1_extraction/
├── main.py
├── output/
│   ├── json/
│   ├── excel/
│   ├── markdown/
│   └── batches/
├── .venv/
├── src/
│   └── doc_extractor/
│       ├── __init__.py
│       ├── __main__.py
│       ├── api.py
│       ├── app.py
│       ├── cli.py
│       ├── core/
│       │   ├── environment.py
│       │   ├── models.py
│       │   ├── patterns.py
│       │   ├── word_parser.py
│       │   ├── pdf_parser.py
│       │   ├── paddle_pdf_parser.py
│       │   ├── cloud_api_parser.py
│       │   ├── pdf_renderer.py
│       │   ├── device_status.py
│       │   ├── paddle_structure.py
│       │   ├── table_models.py
│       │   ├── extractor.py
│       │   ├── exporters.py
│       │   ├── batch_io.py
│       │   ├── environmental_models.py
│       │   ├── environmental_common.py
│       │   ├── environmental_enterprise.py
│       │   ├── environmental_monitoring_extractor.py
│       │   ├── environmental_management_extractor.py
│       │   ├── environmental_statistics_extractor.py
│       │   ├── environmental_pipeline.py
│       │   └── extraction_batch.py
│       └── ui/
│           ├── main_window.py
│           └── worker.py
├── tests/
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── README.md
```

## 测试

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
uv run python -m pytest -q
```

新增 PDF 表格测试使用独立的模拟样本与标准答案（`tests/table_test_support.py`、
`tests/pdf_table_special/`），不修改原有 `test_data/` 与 21 条标准答案。
单引擎调用路径测试位于 `tests/test_ocr.py` 与
`tests/pdf_table_special/test_single_engine_contract.py`。
无界面 API、批次保存/恢复、Markdown 与 CLI 测试位于 `tests/test_api_cli.py`。

真实 PP-StructureV3 模型测试默认跳过，需要显式启用：

```powershell
$env:PADDLE_PDX_CACHE_HOME = "<仓库根目录>/project1_extraction/.paddlex_cache"
$env:RUN_PADDLE_STRUCTURE_TESTS = "1"
uv run python -m pytest tests\test_paddle_real.py -q
```

真实测试数据与标准答案位于 `test_data/`。生成 Markdown 测试报告和 Excel 对比结果：

```powershell
uv run python tests\generate_test_report.py
```

生成文件：

- `docs/项目一_环境数据提取测试报告.md`
- `docs/项目一_环境数据对比结果.xlsx`

测试覆盖：

- Word 解析与 PDF 单引擎解析、表格、页码、坐标、PaddleOCR 文本。
- 环境监测、环保管理、环境统计三类提取。
- 不同单位（`mg/L`、`mg/m3`、`dB(A)`、`m3`、`kWh`、`万m3`、`吨`、`t/a`）。
- 缺失单位、缺失值、检出限表达、数值歧义。
- 多个文件关联同一企业、不同企业隔离、企业身份不明确不自动合并。
- 来源位置、页码、坐标、原始表达追踪。
- JSON/Excel/Markdown 导出。
- 无界面 API、批次保存、批次恢复、JSON 导入。
- CLI 的 `extract` / `export` 子命令与批次导出。
- 重复保存/导出不覆盖已有结果。
- PySide6 环境数据分类视图与后台线程。
- 普通/扫描/混合 PDF 表格识别。
- 有边框、无边框、多级表头、合并单元格、空白单元格。
- 污染指标与数值、单位、点位、日期关联。
- 统一表格模型的图像/PDF 坐标转换。
- PDF 解析引擎固定为 PaddleOCR、禁止 RapidOCR/PyMuPDF 内容解析。
- 本地/云端双模式统一解析接口、模式切换、云端上传确认。
- 云端 API Token 缺失、断网、超时、失败不回退本地。
- 本地与云端统一 JSON/Excel 字段（提取引擎、解析模式）。
- PDF 原页预览与表格待核实信息。

## 已知限制

- 三类业务识别为基础规则版本，指标字典有限，可逐步扩展更多行业字段。
- 企业归并仅支持统一社会信用代码或完全一致企业名称，不做模糊匹配。
- 时间/点位仅在原文明确且无歧义时使用上下文；无法确定时保留缺失标记。
- 不进行单位换算、数值计算、排放量核算或合规判断。
- 不提供 AI 审核和 Word 批注。
- Markdown 仅用于人工阅读，不作为项目二的主要数据交换格式；项目二应读取 JSON。
- CLI 的 `local_gpu` PDF 提取仍需要本地 PaddleOCR 模型；`cloud_api` 仍需要 Token 和网络。
- Word 仅支持 `.docx`，不支持旧版 `.doc`。
- 复杂合并单元格、无线框 PDF 表格仍可能识别不完整。
- PP-StructureV3 对复杂多级表头、跨行跨列表格可能发生列错位或表头行误判，程序会标记 `needs_review`，但仍需人工核对。
- PaddleOCR 结果可能存在识别误差，需人工核对；不会用 OCR 结果补全缺失数据。
- 所有 PDF 均依赖 PP-StructureV3 模型；复杂版式准确率低于简单电子版表格。
- PaddleOCR 失败时返回明确错误，不会回退 RapidOCR 或 PyMuPDF 文字/表格解析。
- 首次下载 PP-StructureV3 模型约 900 MB，初始化耗时较长；后续使用本地缓存。
- 模型初始化后常驻内存较高；实测首次加载后进程 RSS 约 1.4 GB，连续解析多份文档后约 3.3 GB。
- 当前机器 Paddle 为 CPU 版，本地模式实际使用 CPU；未验证真实 GPU 推理。
- PDF 初始化关闭 MKLDNN（`enable_mkldnn=False`），CPU 推理速度较慢；这是规避 PIR/MKLDNN 兼容性错误的必要配置。
- 云端模式需要网络、有效 Token 和可用配额；真实云端 API 准确率需在配置 Token 后单独验证。
- 云端模式会将 PDF 上传到远程服务，界面会在提取前确认；不会自动切换到云端。
- 不支持“二〇二四年五月一日”等中文大写日期格式。
