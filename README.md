# 企业环境数据智能审核系统

- 系统交付基线：**V1.0.0**
- 基线日期：2026-11-01
- 项目根目录：`D:\DocumentAuditSystem`
- 运行形态：命令行（CLI）系统，不含 GUI 或 Web 界面

> V1.0.0 是系统交付基线标识，不等于三个 Python 包的版本号。三个子项目仍分别使用各自 `pyproject.toml` 中的版本：
> 项目一 0.6.0、项目二 0.1.0、项目三 0.1.0。

## 1. 系统简介

本系统用于企业环境数据文档的提取、审核和交付，由三个相互独立的子项目组成：

| 项目 | 目录 | 职责 |
| --- | --- | --- |
| 项目一 | `project1_extraction` | 解析 Word/PDF，生成标准化批次 JSON 和环境数据记录 |
| 项目二 | `project2_word_audit` | 读取批次 JSON，做数学表达式校验、保守错别字检查、定位和批注 |
| 项目三 | `project3_cli_workflow` | 通过 CLI 编排项目一和项目二，管理任务、复用、恢复、日志和最终交付 |

当前审核能力以规则和人工维护词典为基础，不是完整的 AI 智能审核系统。项目一不负责审核，项目二不负责文档解析，项目三不重新计算审核结论。

## 2. 系统建设目标

1. 支持 Word（`.docx`）和 PDF 的统一提取，保留页码、段落、表格、行列和坐标来源。
2. 提取环境监测、环保管理、环境统计三类环境数据，并保留原始表达和待核实标记。
3. 对明确的数学表达式做计算校验，对常见中文错别字做保守检查。
4. 将确认的问题定位回原始 Word 段落/表格单元格或 PDF 页面区域，并生成批注副本。
5. 通过统一 CLI 完成任务编排、输入指纹、阶段复用、断点恢复、日志和最终交付。
6. 保证原始文件只读，输出独立，不覆盖历史任务和验收结果。

## 3. 三个子项目的职责

### 3.1 project1_extraction

- 支持 `.docx` 和 `.pdf`，不支持旧版 `.doc`。
- Word：提取正文、标题、表格、段落/表格/行列索引。
- PDF：统一使用 PaddleOCR PP-StructureV3，支持 `local_gpu` 和 `cloud_api` 两种模式。
- `local_gpu` 是模式标签；当前环境实际 Paddle 设备为 **CPU**，CUDA 不可用。
- PDF 初始化参数包含 `enable_mkldnn=False`，用于规避 PaddlePaddle 3.3.1 CPU/PIR 路径上的 `ConvertPirAttribute2RuntimeAttribute` 错误；关闭 MKLDNN 后 CPU 推理速度较慢。
- 输出批次 JSON（`schema_version = "1.0"`）、环境数据、企业归并结果、来源位置和待核实标记。
- 不做自动计算、合规判断、AI 审核或批注。

### 3.2 project2_word_audit

- 读取项目一 `schema_version = "1.0"` 的 `batch.json`。
- 识别明确的数学表达式并校验结果；普通监测数值不会被误判为计算错误。
- 使用人工维护词典检查常见错别字和已知重复字，不做拼音纠错或任意编辑距离猜词。
- 将问题定位到 Word 段落/表格单元格或 PDF 页面 bbox。
- 仅对 `located` 且允许自动批注的问题生成批注副本。
- Word 批注是在原文段落之后或表格单元格内写入的 **红色文字段落**，不是 Word 原生审阅批注/修订记录。
- PDF 批注是在页面对应区域绘制红色矩形描边。
- 生成审核报告、批注报告和数学校验报告；不修改原始 Word/PDF。

### 3.3 project3_cli_workflow

- 通过子进程调用项目一和项目二正式 CLI，不导入其内部模块。
- 计算输入 SHA-256 和任务指纹，生成任务目录和 `manifest.json`。
- 管理提取、审核、交付三个阶段状态。
- 对有效阶段进行复用；相同输入重复运行不会再次调用项目一或项目二。
- 支持 `resume` 断点恢复和 `deliver` 重新生成交付。
- 生成 `03_delivery` 最终交付目录、审核报告汇总、运行摘要和交付清单。
- 记录两个子项目的 stdout/stderr，并对 Token 做脱敏处理。

## 4. 系统总体架构

```text
用户输入 Word/PDF 或文件夹
        |
        v
project3 输入解析、过滤、SHA-256、任务指纹
        |
        +--> 找到有效任务：复用有效阶段
        |
        +--> 未找到：创建新任务
        |
        v
project1_extraction extract（独立子进程）
        |
        v
batch.json（schema_version = 1.0）
        |
        v
project3 校验 batch.json
        |
        v
project2_word_audit audit（独立子进程）
        |
        v
审核报告 / 批注报告 / 数学校验报告 / 批注副本
        |
        v
project3 03_delivery 最终交付
        |
        v
manifest.json、审核报告汇总、运行摘要、交付清单、日志
```

项目三不复制项目一、项目二的依赖；三个子项目分别使用自己的 `.venv`。

## 5. 数据处理流程

1. **输入阶段**：扫描文件或文件夹，只接受 `.docx` 和 `.pdf`；重复文件和不支持的文件写入 `filtered_inputs`。计算每个输入的大小和 SHA-256。
2. **任务指纹**：根据输入路径、SHA-256、大小、解析模式、项目路径、Python 解释器和项目版本计算任务指纹。Token 不进入指纹。
3. **提取阶段**：项目一生成 `batch.json`。项目三校验 `schema_version`、`batch_id`、文档数量、`environmental`、文档错误和文件类型。
4. **审核阶段**：项目二读取批次，执行数学表达式校验、错别字检查、定位和批注，输出真实审核报告。
5. **交付阶段**：项目三读取审核报告，生成 `03_delivery`，复制真实批注文件，写入 `交付清单.json` 和 `运行摘要.md`。
6. **复用/恢复**：相同输入和配置命中任务时复用有效阶段；输入或配置变化时拒绝错误复用；`resume` 从第一个无效阶段继续。

## 6. 环境和依赖要求

| 项目 | 实际基线 |
| --- | --- |
| 操作系统 | Windows 10/11 x64（本机 Windows NT 10.0.26100.0） |
| Python | 3.12.10 |
| uv | 0.13.6 |
| 项目一 | 0.6.0 |
| 项目二 | 0.1.0 |
| 项目三 | 0.1.0 |
| PaddlePaddle | 3.3.1（CPU 版） |
| PaddleOCR | 3.7.0 |
| PyMuPDF（项目一） | 2.0 |
| PyMuPDF（项目二） | 1.28.2 |
| PySide6（项目一） | 6.12.0 |
| pydantic（项目三） | 2.14.2 |
| typer（项目三） | 0.27.3 |

Paddle 实际状态：

```text
is_compiled_with_cuda() = False
paddle.device.cuda.device_count() = 0
paddle.device.get_device() = cpu
```

因此 `local_gpu` 不代表实际 GPU 推理。当前未验证真实 GPU 推理。

## 7. 项目目录结构

```text
D:\DocumentAuditSystem\
├── README.md                         # 本文件
├── docs\
│   ├── 版本与环境清单.md
│   ├── 测试与验收总报告.md
│   ├── 已知问题与限制.md
│   └── 版本冻结与文档同步报告.md
├── project1_extraction\              # Word/PDF 提取
│   ├── src\doc_extractor\
│   ├── tests\
│   ├── test_data\
│   ├── docs\
│   ├── main.py
│   └── README.md
├── project2_word_audit\              # 数学审核、错别字、定位、批注
│   ├── src\word_audit\
│   ├── tests\
│   ├── test_data\
│   ├── docs\
│   ├── main.py
│   └── README.md
├── project3_cli_workflow\            # 统一 CLI 编排和交付
│   ├── src\project3_cli_workflow\
│   ├── tests\
│   ├── docs\
│   └── README.md
└── acceptance_mixed_20261101_184923\ # 混合验收目录（不属于版本冻结内容）
```

## 8. 安装和运行方式

### 8.1 准备三个虚拟环境

项目一、项目二、项目三分别创建并安装依赖：

```powershell
cd D:\DocumentAuditSystem\project1_extraction
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .

cd D:\DocumentAuditSystem\project2_word_audit
uv sync

cd D:\DocumentAuditSystem\project3_cli_workflow
uv sync
```

项目三默认使用同级目录下项目一、项目二的 `.venv`。如路径不同，可通过 `--project1-root`、`--project1-python`、`--project2-root`、`--project2-python` 指定。

### 8.2 运行完整工作流

```powershell
cd D:\DocumentAuditSystem\project3_cli_workflow
uv run project3 run `
  "D:\DocumentAuditSystem\project1_extraction\test_data\01_企业废水监测报告.docx" `
  "D:\DocumentAuditSystem\project1_extraction\test_data\02_企业废气监测报告.pdf" `
  --output-root "D:\AuditOutput"
```

文件夹输入：

```powershell
uv run project3 run "D:\待审核资料" --output-root "D:\AuditOutput"
uv run project3 run "D:\待审核资料" --recursive --output-root "D:\AuditOutput"
```

### 8.3 断点恢复

```powershell
uv run project3 resume <job_id> --output-root "D:\AuditOutput"
```

### 8.4 重新生成交付

```powershell
uv run project3 deliver --manifest "D:\AuditOutput\<job_id>\manifest.json"
```

### 8.5 查看帮助

```powershell
uv run project3 --help
uv run project3 run --help
uv run project3 resume --help
uv run project3 deliver --help
```

项目一和项目二的独立 CLI 用法见各自 README。

## 9. Word + PDF 混合审核示例

1. 准备待审核的 `.docx` 和 `.pdf` 文件，放到同一目录或分别指定。
2. 执行：

```powershell
cd D:\DocumentAuditSystem\project3_cli_workflow
uv run project3 run `
  "D:\待审核资料\企业废水监测报告.docx" `
  "D:\待审核资料\企业废气监测报告.pdf" `
  --output-root "D:\AuditOutput"
```

3. 命令退出码为 `0` 表示成功；为 `3` 表示部分完成或存在人工核实/缺失交付项；为 `4` 表示外部阶段失败；为 `5` 表示内部错误或锁冲突。
4. 打开 `D:\AuditOutput\<job_id>\03_delivery\运行摘要.md` 和 `审核报告.md` 查看结果。
5. 如存在可批注问题，批注副本位于 `03_delivery\批注文件\`。

验收实测（2026-11-01）：5 个 Word/PDF 文档全部提取成功，2 个 PDF 均成功解析；21 条环境数据与标准答案 21/21 匹配；正式样本未发现问题，因此正式交付没有批注文件。补充错别字样本成功定位并生成批注副本。

## 10. 结果输出和交付目录

```text
<输出根目录>/<job_id>/
├── manifest.json                     # 任务状态、输入、指纹、阶段历史、产物路径
├── 00_inputs/
│   └── input_manifest.json           # 输入清单、SHA-256、过滤记录
├── 01_extraction/
│   ├── batches/<batch_id>/batch.json # 项目一权威批次
│   └── json/<batch_id>.json
├── 02_audit/
│   ├── reports/                      # 审核、批注、数学校验报告
│   └── annotated/                    # 项目二批注副本（如有）
├── 03_delivery/
│   ├── 审核报告.json
│   ├── 审核报告.md
│   ├── 批注文件/
│   ├── 运行摘要.md
│   └── 交付清单.json
└── 04_logs/                          # 项目一、项目二 stdout/stderr
```

阅读重点：

- `manifest.json` 的 `overall_status`、`extraction_status`、`audit_status`、`delivery_status` 是任务状态权威来源。
- `complete_success=true` 只表示项目二流程完整，不代表数据合规。
- `unverified` 表示没有可验证的明确计算表达式，不是错误。
- `manual_review` 需要人工复核，不是已确认错误。
- 交付清单记录每个 artifact 的大小和 SHA-256。

## 11. 测试结果

2026-11-01 实际执行结果：

| 项目 | 测试数 | 通过 | 失败 | 跳过 | 其他 |
| --- | ---: | ---: | ---: | ---: | --- |
| 项目一 | 134 | 134 | 0 | 0（2 项补跑后） | 1 warning |
| 项目二 | 125 | 125 | 0 | 0 | OK |
| 项目三 | 150 | 150 | 0 | 0 | Ruff 通过 |

混合端到端验收：

- 5 个 Word/PDF 文档全部提取成功。
- 两个 PDF 均成功解析，未再出现 PIR/MKLDNN 错误。
- 21 条环境数据与标准答案 21/21 匹配。
- 相同输入三阶段全部复用；交付阶段恢复成功。
- 部分成功和全部失败状态均正确区分。
- 原始文件、测试数据、源代码和依赖未发生意外变化。

详细结果见 `docs/测试与验收总报告.md`。

## 12. 已知限制

1. PDF 使用 CPU 推理，速度较慢；Paddle CUDA 当前不可用。
2. `local_gpu` 是模式标签，实际设备为 `cpu`，容易误解。
3. 项目二审核能力以规则和人工词典为主，不是完整 AI 智能审核。
4. Word 批注是红色文字段落，不是 Word 原生审阅批注/修订记录。
5. 正式真实样本 21 条均为 `unverified`，不能据此认定所有业务规则均已验证。
6. 偶发 `WinError 5`：隔离的部分成功任务中交付目录重命名曾失败一次，`resume` 后恢复成功，重跑未复现。
7. `00_inputs/input_manifest.json` 中每个输入的 `status` 可能保持 `pending`，实际状态看 `manifest.json` 和 `batch.json`。
8. Word 表格值可进入环境数据记录，但文档级 `table_count` 可能为 0，`tables` 数组可能为空。
9. 项目三未实现 GUI、Web、跨机器分布式锁和首次并发全局去重。
10. 未验证真实 GPU 推理；未执行云端 API 真实调用。

详细说明见 `docs/已知问题与限制.md`。

## 13. 安全和数据保护说明

- 原始 Word/PDF 只读，项目二批注只写入新副本。
- 项目三只向任务目录写入，不覆盖历史任务目录或验收结果。
- 不硬编码、不显示、不写日志、不提交 API Token。
- `PADDLEOCR_ACCESS_TOKEN` 只从环境变量读取；云端模式必须显式指定 `--mode cloud_api`，且会上传 PDF。
- 默认使用 `local_gpu`；本次验收未调用云端 API，未设置 Token。
- 任务锁为单机文件锁，不是分布式锁。
- 版本冻结只包含 Markdown 文档，不包含测试输出、模型文件、Token 或个人数据。

## 14. 版本信息

| 标识 | 值 |
| --- | --- |
| 系统交付基线 | `V1.0.0` |
| 项目一 Python 包版本 | `0.6.0` |
| 项目二 Python 包版本 | `0.1.0` |
| 项目三 Python 包版本 | `0.1.0` |
| 最后一次完整验收日期 | 2026-11-01 |
| 验收结论 | 有条件通过 |

相关文档：

- `docs/版本与环境清单.md`
- `docs/测试与验收总报告.md`
- `docs/已知问题与限制.md`
- `docs/版本冻结与文档同步报告.md`
- `acceptance_mixed_20261101_184923/混合Word_PDF端到端验收报告.md`
- `project1_extraction/docs/PaddleOCR_PDF兼容性修复报告.md`
