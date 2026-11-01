# 企业环境数据智能审核系统 CLI 工作流（project3_cli_workflow）

## 项目总体介绍

本项目是企业环境数据智能审核系统的统一命令行工作流，负责调度三个相互独立的子项目：

1. `project1_extraction`：Word/PDF 信息提取。
2. `project2_word_audit`：数学计算校验、错别字检查、问题定位及批注。
3. `project3_cli_workflow`：统一调度、任务指纹、阶段复用、断点恢复、日志和最终交付。

项目三不开发 GUI 或 Web 界面，只提供 CLI。

## 三个子项目的职责

### project1_extraction

- 解析 `.docx` 和 `.pdf`。
- 生成项目一批次 JSON：`output/batches/<batch_id>/batch.json`。
- 不进行审核、计算校验或批注。

### project2_word_audit

- 读取项目一 `schema_version = "1.0"` 的批次 JSON。
- 进行数学校验和保守中文错别字检查。
- 定位 Word 段落、表格单元格、PDF 页面位置。
- 生成审核报告、批注报告和批注副本。
- 不修改原始 Word/PDF。

### project3_cli_workflow

- 调用项目一和项目二 CLI。
- 管理任务目录、manifest、阶段状态和日志。
- 计算输入 SHA-256 和任务指纹。
- 对有效阶段进行复用。
- 支持 `resume` 断点恢复。
- 生成 `03_delivery` 最终交付目录。

## 系统工作流程

```text
用户输入 Word/PDF 或文件夹
        |
        v
输入解析、过滤、SHA-256
        |
        v
任务指纹匹配
        |
        +--> 找到有效任务：复用有效阶段
        |
        +--> 未找到：创建新任务
        |
        v
项目一 extract
        |
        v
校验 batch.json
        |
        v
项目二 audit
        |
        v
读取审核报告
        |
        v
生成 03_delivery 最终交付
        |
        v
输出 manifest、审核报告、运行摘要和交付清单
```

## 目录结构

```text
project3_cli_workflow/
├── pyproject.toml
├── README.md
├── src/
│   └── project3_cli_workflow/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── inputs.py
│       ├── manifest.py
│       ├── models.py
│       ├── errors.py
│       ├── process.py
│       ├── project1.py
│       ├── project2.py
│       ├── delivery.py
│       ├── fingerprint.py
│       ├── reuse.py
│       └── lock.py
├── tests/
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_delivery.py
│   ├── test_errors.py
│   ├── test_fingerprint.py
│   ├── test_inputs.py
│   ├── test_lock.py
│   ├── test_manifest.py
│   ├── test_process.py
│   ├── test_project1.py
│   ├── test_project2.py
│   └── test_reuse.py
├── docs/
│   ├── 项目一与项目二接口调研报告.md
│   ├── 系统架构说明.md
│   ├── 用户使用手册.md
│   └── 测试与验收报告.md
├── examples/
├── logs/
└── .venv/
```

## 环境要求

- Windows 10/11 x64
- Python 3.12（当前验证 3.12.10）
- uv 0.13.6
- 项目一、项目二各自已创建 `.venv`
- 项目一 PDF 解析依赖 PaddleOCR/PaddlePaddle

## 安装

```powershell
cd D:\DocumentAuditSystem\project3_cli_workflow
uv sync
```

项目一、项目二使用各自虚拟环境，项目三不复制其依赖。

## 运行方式

### 正常运行

```powershell
uv run project3 run "<Word或PDF路径>" --output-root "<输出根目录>"
```

多种输入：

```powershell
uv run project3 run "文件1.docx" "文件2.pdf" --output-root "D:\AuditOutput"
```

文件夹输入：

```powershell
uv run project3 run "D:\待审核资料" --output-root "D:\AuditOutput"
```

递归扫描：

```powershell
uv run project3 run "D:\待审核资料" --recursive --output-root "D:\AuditOutput"
```

### 断点恢复

```powershell
uv run project3 resume <job_id> --output-root "<输出根目录>"
```

### 重新生成交付

```powershell
uv run project3 deliver --manifest "<任务目录>\manifest.json"
```

### 查看帮助

```powershell
uv run project3 --help
uv run project3 run --help
uv run project3 resume --help
uv run project3 deliver --help
```

## 输出结果说明

任务目录示例：

```text
<输出根目录>/<job_id>/
├── manifest.json
├── 00_inputs/
│   └── input_manifest.json
├── 01_extraction/
│   ├── batches/<batch_id>/batch.json
│   └── json/<batch_id>.json
├── 02_audit/
│   ├── reports/
│   └── annotated/
├── 03_delivery/
│   ├── 审核报告.json
│   ├── 审核报告.md
│   ├── 批注文件/
│   ├── 运行摘要.md
│   └── 交付清单.json
└── 04_logs/
```

`manifest.json` 记录：

- 任务 ID、输入文件、SHA-256。
- 任务指纹和指纹组件。
- 提取、审核、交付状态。
- 阶段复用标记。
- 阶段历史。
- 真实产物路径。
- 错误和警告。

## 状态和退出码

任务整体状态：

```text
success / partial / failed
```

CLI 退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `2` | 用户输入错误 |
| `3` | 部分完成 / 存在人工核实或缺失交付项 |
| `4` | 外部阶段失败 |
| `5` | 内部错误或任务锁冲突 |

## 已知问题与限制

1. 项目一本地 PDF 使用 PaddleOCR PP-StructureV3 CPU 推理：
   - `local_gpu` 是模式标签；当前 Paddle 为 CPU 版，实际设备为 `cpu`。
   - PP-StructureV3 初始化已设置 `enable_mkldnn=False`，用于规避原 `ConvertPirAttribute2RuntimeAttribute not support` 错误。
   - 该修复已通过混合 Word + PDF 真实验收和项目一完整回归测试；关闭 MKLDNN 后 CPU 推理速度较慢。
   - 若 PDF 仍解析失败，项目三会记录 `extraction_partial` 或 `extraction_failed`，不会伪装成功。

2. 项目二当前是规则审核：
   - 数学计算校验
   - 保守错别字词典
   - 定位与批注

它不是完整的 AI 智能审核系统。

3. `complete_success=True` 只表示项目二流程完整，不代表所有数据合规。

4. `unverified` 不是错误，只表示没有可验证的明确计算表达式。

5. `manual_review` 不是已确认错误，需要人工复核。

6. 项目一仅支持 `.docx` 和 `.pdf`，不支持旧版 `.doc`。

7. 项目三当前未实现 GUI、Web、跨机器分布式锁和首次并发运行的全局去重。

## 相关文档

- `docs/项目一与项目二接口调研报告.md`
- `docs/系统架构说明.md`
- `docs/用户使用手册.md`
- `docs/测试与验收报告.md`
