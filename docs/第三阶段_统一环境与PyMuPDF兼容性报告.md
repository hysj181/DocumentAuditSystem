# 第三阶段：统一环境与 PyMuPDF 兼容性报告

- 报告日期：2026-11-07
- Git 分支：`refactor/v2-architecture`
- 统一环境：`D:\DocumentAuditSystem\project3_web\.venv`
- Python：3.12.10
- uv：0.13.6
- 结论：**统一环境验证通过（有条件）**

> 本阶段未删除或覆盖项目一、项目二、项目三原有 `.venv`；未修改项目一 PaddleOCR PDF 兼容性修复；未修改原始 `test_data`；未使用跳过条件隐藏问题。  
> 原有 Word 红字标记仍未改为原生审阅批注，本报告不将其描述为原生批注。

---

## 1. 新环境目录和 Python 版本

| 项 | 值 |
| --- | --- |
| 环境目录 | `D:\DocumentAuditSystem\project3_web\.venv` |
| Python | 3.12.10 |
| `.python-version` | `3.12.10` |
| uv | 0.13.6 |
| 已安装发行包数量 | 137 |
| 环境体积 | 约 1,757.9 MiB（约 1.72 GiB） |
| `uv sync --locked` | 成功，检查 137 个包 |

旧环境保留：

- `project1_extraction\.venv`
- `project2_word_audit\.venv`
- `project3_cli_workflow\.venv`

旧环境均未删除、未覆盖、未执行 `sync`。

---

## 2. 统一依赖清单

### 2.1 关键运行依赖

| 依赖 | 统一环境版本 | 说明 |
| --- | ---: | --- |
| PyMuPDF | 2.0 | 固定，不使用 2.1 |
| pymupdf-layout | 2.0 | PyMuPDF 2.0 传递依赖 |
| pymupdf4llm | 2.0 | PyMuPDF 2.0 传递依赖 |
| onnxruntime | 1.31.1 | PyMuPDF 2.0 传递依赖 |
| numpy | 2.3.5 | 固定 |
| PaddlePaddle | 3.3.1 | 固定 |
| PaddleOCR | 3.7.0 | 固定 |
| paddlex | 3.7.2 | 以 `paddlex[ocr]==3.7.2` 声明 |
| python-docx | 1.2.0 | 固定 |
| PySide6 | 6.12.0 | 项目一 GUI 依赖 |
| FastAPI | 0.162.0 | Web 依赖 |
| Uvicorn | 0.54.0 | Web 依赖 |
| Jinja2 | 3.1.6 | Web 依赖 |
| python-multipart | 0.0.33 | Web 上传依赖 |
| pydantic | 2.14.2 | 固定 |
| typer | 0.27.3 | 固定 |
| rich | 15.0.0 | 固定 |
| pytest | 9.2.0 | 开发依赖 |
| ruff | 0.17.4 | 开发依赖 |
| PyYAML | 6.0.2 | 传递依赖 |

### 2.2 PyMuPDF 传递依赖核对

核实结果：

1. `pymupdf-layout` 与 `pymupdf_layout` 是**同一个发行包**，只是名称规范化不同。  
   - 环境内只有 `pymupdf_layout-2.0.dist-info`。
   - `uv.lock` 中只有一份 `[[package]] name = "pymupdf-layout"`。
   - 没有重复安装两份，也没有手动重复声明。
2. `pymupdf4llm` 实际版本为 `2.0`。
3. `onnxruntime` 实际版本为 `1.31.1`。
4. `numpy` 在统一环境中最终解析为 `2.3.5`。
5. 未发现重复依赖声明。

### 2.3 发现并修复的 PaddleOCR 依赖缺口

统一环境首次同步后，`PP-StructureV3` 初始化失败：

```text
DependencyError: `PP-StructureV3` requires additional dependencies.
```

原因：`paddleocr` 只声明 `paddlex[ocr-core]`，但 PP-StructureV3 实际需要 `paddlex[ocr]` 的额外依赖（如 scipy、scikit-learn、sentencepiece、tokenizers 等）。  
处理：在 `project3_web/pyproject.toml` 中显式加入：

```toml
"paddlex[ocr]==3.7.2"
```

重新 `uv lock` 和 `uv sync` 后，PP-StructureV3 初始化成功，真实 PaddleOCR 测试通过。  
未升级 PaddlePaddle、PaddleOCR，仅补齐其运行所需的可选依赖。

---

## 3. PyMuPDF 版本及兼容性结论

### 3.1 版本固定

统一环境固定：

```text
pymupdf==2.0
```

项目二依赖由 `pymupdf<2` 调整为：

```text
pymupdf==2.0
```

项目一仍为 `PyMuPDF>=1.24`，统一环境通过显式固定解析到 2.0。  
未安装、未解析、未使用 PyMuPDF 2.1。

### 3.2 兼容性结论

- 1.28.2 → 2.0 的仓库实际调用 API 签名一致。
- 真实 PDF 定位、PDF 红色矩形批注在 2.0 下通过。
- 真实 Word 表格/段落定位与批注在 2.0 下通过。
- 项目一真实 PaddleOCR 扫描 PDF、表格坐标、PDF 兼容性测试在 2.0 下通过。
- 未修改项目一 `paddle_structure.py`、`pdf_parser.py`。
- 结论：**当前仓库实际使用的 PyMuPDF API 在 2.0 下兼容，真实 PDF 回归通过。**

### 3.3 性能注意

PyMuPDF 2.0 的 import 明显慢于 1.28.2，详见第 8 节。2.1 修复了该问题，但本阶段按要求未采用 2.1。

---

## 4. 项目二 43 项跳过测试的分类和处理结果

### 4.1 分类

43 项全部因同一个原因跳过：

```text
real batch not found:
project1_extraction/output/batches/20261101T053459830362Z_0e022780/batch.json
```

| 测试模块 | 数量 | 覆盖内容 |
| --- | ---: | --- |
| `test_annotation.py` | 11 | Word 段落/表格批注、PDF 红色矩形、多批注、原文哈希保持 |
| `test_location.py` | 20 | Word 段落/表格定位、PDF bbox 定位、歧义/失败/人工核实 |
| `test_pipeline.py` | 4 | 真实批次完整审核、CLI 审核、真实批次非合成标记 |
| `test_real_batch_validation.py` | 7 | 9 条真实环境记录、指标/数值/单位、检限、报表字段 |
| `test_typo_pipeline.py` | 1 | 真实批次错别字统计一致性 |
| **合计** | **43** | |

### 4.2 夹具实现

新增：

- `project2_word_audit/tests/real_batch_support.py`
- `project2_word_audit/tests/conftest.py`

实现方式：

1. pytest **session 级 autouse fixture** 在整个测试会话中只构建一次真实批次。
2. 输入固定为：
   - `project1_extraction/test_data/01_企业废水监测报告.docx`
   - `project1_extraction/test_data/02_企业废气监测报告.pdf`
3. 使用项目一 `extract_files()` 真实提取。
4. 将 `batch_id` 固定为历史值 `20261101T053459830362Z_0e022780`。
5. 使用 `save_batch()` 写入 pytest `tmp_path_factory` 临时目录。
6. 校验夹具形状：
   - 2 个文档；
   - 9 条环境记录；
   - Word 5 个段落、6×4 表格；
   - 指标顺序与既有测试常量一致；
   - 表格关键值 `85`、`12.5` 一致。
7. 夹具创建失败时直接报错，不 skip。
8. 所有原 `skipUnless` 已删除；`setUpClass` 通过 `real_batch_path()` 获取已初始化批次。
9. 43 项测试的全部原断言保留。

### 4.3 处理结果

- 43 项跳过测试全部转为实际执行。
- 项目二完整测试结果：**125 passed，0 failed，0 skipped，66 subtests passed**。
- 真实批次夹具单独冒烟：**7 passed，18 subtests passed**。
- 未通过增加 skip 获得绿色结果。

---

## 5. 三个项目的测试结果

统一环境解释器：

```text
D:\DocumentAuditSystem\project3_web\.venv\Scripts\python.exe
```

| 测试项 | 退出码 | 通过 | 失败 | 跳过 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 项目一完整测试（统一环境） | 0 | 132 | 0 | 2（真实 Paddle 门控） | 1303.37s（21:43） |
| 项目一真实 Paddle 补跑 | 0 | 2 | 0 | 0 | 131.02s（02:11） |
| 项目一合计 | 0 | **134** | **0** | **0** | 约 1434s |
| 项目二完整测试（统一环境） | 0 | **125** | **0** | **0** | 76.16s |
| 项目三完整测试（统一环境） | 0 | **150** | **0** | **0** | 3.09s |
| project3_web 集成测试 | 0 | **2** | **0** | **0** | 53.99s |

补充检查：

| 检查 | 结果 |
| --- | --- |
| 同解释器导入 `doc_extractor`、`word_audit`、`project3_cli_workflow`、`project3_web` | 通过 |
| `uv lock --check`（项目一） | 退出码 0 |
| `uv lock --check`（项目二） | 退出码 0 |
| `uv lock --check`（project3_web） | 退出码 0 |
| `uv sync --locked`（project3_web） | 成功 |
| `ruff check`（project3_web） | 通过 |
| `ruff check`（项目三） | 通过 |
| `ruff check`（项目二新增/修改测试） | 通过 |

---

## 6. 真实 PDF 测试结果

| 测试 | 结果 |
| --- | --- |
| 项目一真实 `test_data` 全量测试 | 通过（包含在 132 passed） |
| 项目一真实 Paddle 扫描件测试 | 2 passed，131.02s |
| 项目二真实批次 PDF 页信息 | 1 页，595×842，rotation=0，通过 |
| 项目二真实批次 PDF 定位 | 4 条 PDF 环境记录全部 `located`，bbox 在页面内，通过 |
| 项目二真实批次 PDF 红色矩形批注 | 通过，批注后正文保持，源文件哈希不变 |
| 项目二真实批次 Word 段落/表格定位 | 通过 |
| 项目二真实批次 Word 段落/表格批注 | 通过 |
| PyMuPDF 2.0 下 PDF 定位/批注 | 全部通过 |

说明：项目二原有 Word 批注仍为红色文字段落，不是 Word 原生审阅批注；本阶段未改变该行为，也不将其描述为原生批注。

---

## 7. 混合 Word + PDF 测试结果

### 7.1 project3_web 集成测试

测试内容：

1. FastAPI `/health` 健康检查。
2. 混合 Word + PDF 端到端：
   - 项目一提取 `01_企业废水监测报告.docx` 和 `02_企业废气监测报告.pdf`；
   - 项目二审核；
   - 校验 2 个文档、9 条环境记录；
   - 校验 `record_count=9`、`unverified_count=9`、`issue_count=0`、`complete_success=True`；
   - 校验无批注输出；
   - 校验原始输入 SHA-256 不变。

结果：**2 passed，53.99s**。

### 7.2 统一环境下的旧 CLI 验证

使用统一环境 Python 作为项目一、项目二的解释器，执行项目三 CLI：

```text
project3 run <01.docx> <02.pdf> \
  --project1-python <统一环境 python> \
  --project2-python <统一环境 python>
```

结果：

- 退出码：`0`
- 整体状态：`success`
- 交付状态：`delivery_success`
- unverified：`9`
- 审核问题：`0`
- 交付文件数：`4`
- 缺失交付项：`0`

说明：项目三 CLI 的默认解释器仍指向旧项目 `.venv`；本次通过显式参数验证统一环境，未切换默认环境。

### 7.3 中文+空格工作目录测试

工作目录：

```text
C:\Users\孙强强\AppData\Local\Temp\opencode\跨目录 测试
```

| 测试 | 退出码 | 结果 | 耗时 |
| --- | ---: | --- | ---: |
| 项目一跨目录子集 | 0 | 22 passed | 292.27s |
| 项目二跨目录完整测试 | 0 | 125 passed，66 subtests | 79.28s |
| 项目三跨目录完整测试 | 0 | 150 passed | 3.68s |
| project3_web 跨目录集成测试 | 0 | 2 passed | 71.64s |

---

## 8. 性能对比

### 8.1 PyMuPDF import 耗时

同一台机器，独立进程测量：

| 环境 | PyMuPDF 版本 | 3 次测量（秒） | 中位数 |
| --- | --- | --- | ---: |
| 统一环境 | 2.0 | 0.856 / 0.914 / 0.892 | 0.892 |
| 项目一旧环境 | 2.0 | 1.456 / 0.900 / 0.813 | 0.900 |
| 项目二旧环境 | 1.28.2 | 0.239 / 0.112 / 0.098 | 0.112 |

结论：PyMuPDF 2.0 import 明显慢于 1.28.2，属于已知的 2.0 急切初始化开销；2.1 修复了该问题，但本阶段未采用 2.1。

### 8.2 FastAPI/Uvicorn

| 项 | 耗时 |
| --- | ---: |
| `import fastapi, uvicorn` | 0.618s |
| `create_app()` | 0.036s |

### 8.3 真实提取/测试耗时

| 项 | 耗时 |
| --- | ---: |
| 真实批次夹具构建（2 个文件，含 PaddleOCR） | 约 54–80s |
| 项目二完整测试（含夹具） | 76.16s |
| project3_web 混合端到端测试 | 53.99s |
| 项目一完整测试 | 1303.37s（21:43） |
| 项目一真实 Paddle 补跑 | 131.02s |
| 项目三完整测试 | 3.09s |

### 8.4 环境体积

| 项 | 值 |
| --- | ---: |
| 统一环境大小 | 约 1,757.9 MiB |
| 发行包数量 | 137 |

体积主要来自 PySide6/PySide6-WebEngine、PaddlePaddle/PaddleOCR、onnxruntime、scipy/scikit-learn 等。

---

## 9. 仍存在的问题

1. **项目一独立依赖声明缺少 `paddlex[ocr]`**  
   项目一现有 `.venv` 能正常运行，是因为其中已安装 `paddlex[ocr]` 额外依赖；但其 `pyproject.toml`/`uv.lock` 只声明了 `paddleocr`（解析为 `paddlex[ocr-core]`）。在全新环境中仅按项目一 lock 安装，PP-StructureV3 可能失败。统一环境已通过显式 `paddlex[ocr]==3.7.2` 修复。建议后续单独修正项目一依赖声明并更新其 lock。

2. **PyMuPDF 2.0 import 约 0.89s**  
   比 1.28.2 的 0.11s 慢约 8 倍。2.1 修复该问题，但本阶段未升级 2.1。

3. **统一环境体积约 1.72 GiB**  
   PySide6 及 WebEngine 占比较大。后续可评估将 PySide6 改为可选 extra，但本阶段为保护项目一 GUI/CLI 功能未改动。

4. **项目二独立 lock 的传递版本与统一环境不同**  
   项目二单独 `uv.lock` 已更新为 PyMuPDF 2.0，其新解析的 numpy 为 2.5.4、PyYAML 为 6.0.3；统一环境固定为 numpy 2.3.5、PyYAML 6.0.2。项目二旧 `.venv` 仍为 PyMuPDF 1.28.2，未被修改。正式测试以统一环境为准。

5. **真实批次夹具为 session autouse**  
   任何项目二 pytest 会话都会构建一次真实批次，即使只运行少量非真实批次测试，也会增加约 1 分钟。后续可优化为按需触发，但当前做法满足“整个会话只执行一次”的要求。

6. **Word 批注仍为红色正文文字**  
   本阶段未修改批注实现，不能描述为 Word 原生审阅批注。

7. **项目三仍是 CLI 架构**  
   `project3_web` 目前只有最小 FastAPI 健康检查骨架，正式 Web 上传、任务、下载流程留到第四阶段。

8. **项目三 CLI 默认解释器仍指向旧 `.venv`**  
   未切换默认环境；本阶段通过显式 `--project1-python`/`--project2-python` 验证统一环境。

9. **历史文档尚未全部同步**  
   部分历史报告仍包含旧路径/旧安装方式，计划在第五阶段统一归档和更新。

---

## 10. 回滚方案

如统一环境验证失败或用户要求回滚：

1. 删除新环境目录：
   - `project3_web\.venv`
2. 回退 `project3_web/` 新增文件：
   - `pyproject.toml`
   - `uv.lock`
   - `.python-version`
   - `.gitignore`
   - `src/project3_web/`
   - `tests/test_integration.py`
3. 回退项目二 PyMuPDF 约束和 lock：
   - `project2_word_audit/pyproject.toml` 恢复 `pymupdf<2`
   - `project2_word_audit/uv.lock` 恢复原版本
4. 回退项目二真实批次测试改造：
   - 恢复 5 个测试文件的 `skipUnless` 和原 `BATCH_PATH`
   - 删除 `tests/conftest.py`、`tests/real_batch_support.py`
5. 不触碰：
   - 项目一 `.venv`
   - 项目二 `.venv`
   - 项目三 `.venv`
   - 项目一 PaddleOCR PDF 兼容性代码
   - 原始 `test_data`
   - Git 历史和历史报告

旧环境始终保留，回滚后可直接继续使用原三个 `.venv`。

---

## 11. 阶段结论

本阶段完成了：

- 独立统一 Web 环境创建；
- PyMuPDF 2.0 固定与真实 PDF 回归；
- 项目二 43 项真实批次测试恢复执行；
- 三个项目完整测试；
- 混合 Word + PDF 端到端测试；
- 跨工作目录、中文+空格路径测试；
- 旧 CLI 在统一环境下的兼容性验证；
- 性能与依赖核对。

**统一环境与 PyMuPDF 兼容性验证通过。**  
本阶段结束后暂停，等待用户审核报告，不自动进入第四阶段 Web 改造。
