# PaddleOCR PDF 兼容性修复报告

- 修复时间：2026-11-01
- 修复对象：`D:\DocumentAuditSystem\project1_extraction`
- 修复范围：仅本地 PDF 推理路径的 PP-StructureV3 初始化参数
- 修复结果：**134 项测试全部通过；原 PIR/MKLDNN 错误不再出现；PDF 提取结果与标准答案保持一致**
- 性能提示：关闭 MKLDNN 后 CPU 推理明显变慢，详见第 11 节

---

## 1. 修复原因

修复前，项目一使用以下环境执行本地 PDF 解析：

- PaddlePaddle 3.3.1（CPU 版）
- PaddleOCR 3.7.0
- PaddleX 3.7.2
- PP-StructureV3 本地推理
- PaddleX 在 CPU 上默认 `run_mode=mkldnn`
- PaddleX 对 `PP-DocLayout_plus-L` 默认 `enable_new_ir=True`

实际错误发生在 PP-StructureV3 的第一个模型 `PP-DocLayout_plus-L`：

```text
NotImplementedError:
ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
  at ..\paddle\fluid\framework\new_executor\instruction\onednn\onednn_instruction.cc:118
```

诊断报告已确认：该错误位于 PaddlePaddle 3.3.1 的 PIR 新执行器 + oneDNN/MKLDNN 推理路径，不是 PaddleOCR 参数、PP-StructureV3 调用方式或项目一业务代码的问题。

本次按照指定方案，关闭 PP-StructureV3 的 CPU MKLDNN 推理路径，使 PaddleX 使用普通 `paddle` 静态图推理，从而绕过该 PaddlePaddle 底层缺陷。

---

## 2. 修改文件

### 2.1 修改的源码文件

仅修改 1 个文件：

```text
src\doc_extractor\core\paddle_structure.py
```

### 2.2 新增的报告文件

```text
docs\PaddleOCR_PDF兼容性诊断报告.md   （上一轮诊断报告，已存在）
docs\PaddleOCR_PDF兼容性修复报告.md   （本报告）
```

### 2.3 未修改的文件

以下文件均未修改：

```text
requirements.txt
pyproject.toml
uv.lock
run_project1.bat
src\doc_extractor\core\paddle_pdf_parser.py
src\doc_extractor\core\pdf_parser.py
src\doc_extractor\core\pdf_renderer.py
src\doc_extractor\core\word_parser.py
src\doc_extractor\core\cloud_api_parser.py
tests\  （全部测试）
test_data\  （全部原始测试数据）
D:\DocumentAuditSystem\project2_word_audit\
D:\DocumentAuditSystem\project3_cli_workflow\
```

### 2.4 PPStructureV3 初始化入口检查

在项目一 `src` 中检查到：

| 位置 | 用途 | 本次是否修改 |
| --- | --- | --- |
| `core\paddle_structure.py:585`、`:607` | 本地 PP-StructureV3 推理 | **是** |
| `core\cloud_api_parser.py:115`、`:120` | 云端 API 的 `PPStructureV3Options` | 否 |

本地推理只有 `PaddleStructureParser.__init__` 一个实际初始化入口，因此只修改该位置。云端 API 请求逻辑未改动。

---

## 3. 修改内容

### 3.1 实际差异

修改位置：`src\doc_extractor\core\paddle_structure.py:604`

```diff
             "use_region_detection": False,
             "use_table_recognition": True,
+            "enable_mkldnn": False,
         }
         options.update(kwargs)
         try:
             self._pipeline = PPStructureV3(**options)
```

### 3.2 修改说明

- 保留原有全部初始化参数。
- 未改变 PDF 页面渲染、坐标换算、OCR 文本提取、表格解析逻辑。
- 未改变 `DocumentResult`、`ExtractionRecord`、`TableData`、`EnvironmentalRecord` 数据结构。
- 未改变 Word 提取代码。
- 未改变云端 API 模式。
- 未增加其他推理参数。
- `enable_mkldnn=False` 位于 `options` 字典中，在 `PPStructureV3(**options)` 调用前合并；`options.update(kwargs)` 仍保留原有覆盖能力。
- 运行时已验证该参数传递到实际 PaddleX Runner：版面检测模型配置由 `run_mode=mkldnn` 变为 `run_mode=paddle`。

### 3.3 修改前后源码哈希

| 文件 | 修改前 SHA-256 | 修改后 SHA-256 |
| --- | --- | --- |
| `src\doc_extractor\core\paddle_structure.py` | `0B045F14B6ABC70A90453EF062CB3952F1E20B95B1AACF60485DA1599E2477BB` | `16919E30198A13BC610C52E5D9DE873F3D3A9CD269165BAD6CBD39B4585CF821` |

备份文件：

```text
C:\Users\孙强强\AppData\Local\Temp\opencode\backup_project1_20261101_175159\paddle_structure.py.bak
```

备份 SHA-256：

```text
0B045F14B6ABC70A90453EF062CB3952F1E20B95B1AACF60485DA1599E2477BB
```

备份与修改前源码哈希一致，且备份目录为本次新建，未覆盖已有备份。

---

## 4. 修复前后依赖版本

修复前后依赖版本完全一致，未升级、降级或安装任何包。

| 依赖 | 修复前 | 修复后 |
| --- | --- | --- |
| Python | 3.12.10 | 3.12.10 |
| paddlepaddle | 3.3.1 | 3.3.1 |
| paddlepaddle-gpu | 未安装 | 未安装 |
| paddleocr | 3.7.0 | 3.7.0 |
| paddlex | 3.7.2 | 3.7.2 |
| numpy | 2.3.5 | 2.3.5 |
| protobuf | 7.36.2 | 7.36.2 |
| opencv-python | 5.0.0.93（元数据） | 5.0.0.93（元数据） |
| opencv-contrib-python | 4.10.0.84 | 4.10.0.84 |
| 运行时 `cv2.__version__` | 4.10.0 | 4.10.0 |
| PyMuPDF | 2.0 | 2.0 |
| shapely | 2.2.0 | 2.2.0 |
| pyclipper | 1.4.0 | 1.4.0 |

模型缓存未删除，模型文件时间戳未变化。

---

## 5. 最小 PDF 测试结果

### 5.1 测试对象

```text
tests\pdf_table_special\samples\scanned_special_values.pdf
SHA-256 = E95E4C2167F2690F920E2565597A84FF0E14C6AF2F0C3A1BF74409F61FB75622
```

使用项目一自己的虚拟环境：

```text
D:\DocumentAuditSystem\project1_extraction\.venv\Scripts\python.exe
```

本地推理模式：`local_gpu`（当前 Paddle 实际为 CPU 版，实际设备 `cpu`）。
未调用云端 API，未使用 Token。
临时输出目录：

```text
C:\Users\孙强强\AppData\Local\Temp\opencode\pdf_fix_minimal_out
```

### 5.2 检查结果

| 检查项 | 结果 |
| --- | --- |
| PaddleOCR 初始化 | 成功 |
| PP-StructureV3 初始化 | 成功 |
| 版面检测 Runner | `PaddleStaticRunner` |
| 实际 `run_mode` | `paddle`（不再是 `mkldnn`） |
| 实际设备 | `cpu` |
| `enable_new_ir` | `True` |
| PDF 页面推理 | 成功 |
| 原 PIR/MKLDNN 错误 | 未出现 |
| 结果错误字段 | `error=None` |
| 警告 | `[]` |
| 页面数 | 1 |
| 表格数 | 1 |
| 表格结构 | 9 行 × 5 列，表头 1 行 |
| OCR 文本行 | 55 |
| 提取记录总数 | 57（1 个 `ocr_page` + 55 个 `ocr_text` + 1 个 `table`） |
| 环保数据记录 | 8 |
| 表格 bbox | `[38.878, 114.465, 599.732, 385.868]` |
| `needs_review` | `True`（扫描表格存在待人工核实标记，符合预期） |

### 5.3 文本、表格与环保数据合理性

表格内容与测试样本一致：

```text
监测点位 | 指标 | 数值 | 单位 | 监测日期
DW001 废水总排口 | COD | 45.2 | mg/L | 2024-07-01
DW001 废水总排口 | 总磷 | <0.01 | mg/L | 2024-07-01
DW001 废水总排口 | 悬浮物 | — | mg/L | 2024-07-01
DW001 废水总排口 | pH | 7.3 | 无量纲 | 2024-07-01
DA001 废气排放口 | 二氧化硫 | ND | mg/m3 | 2024-07-02
DA001 废气排放口 | 氮氧化物 | 35.2 | mg/m3 | 2024-07-02
DA001 废气排放口 | 颗粒物 | 8.6 | mg/m3 | 2024-07-02
厂界东侧 | 噪声 | 55.6 | dB(A) | 2024-07-02
```

环保数据提取 8 条，关键字段示例：

| 指标 | 值 | 单位 | 点位 | 时间 | 检出限 |
| --- | --- | --- | --- | --- | --- |
| COD | 45.2 | mg/L | 废水总排口 | 2024-07-01 | — |
| 总磷 | 空值 | mg/L | 废水总排口 | 2024-07-01 | `<0.01` |
| 悬浮物 | 空值 | mg/L | 废水总排口 | 2024-07-01 | — |
| pH | 7.3 | 无量纲 | 废水总排口 | 2024-07-01 | — |
| 二氧化硫 | 空值 | mg/m³ | 废气排放口 | 2024-07-02 | `ND` |
| 氮氧化物 | 35.2 | mg/m³ | 废气排放口 | 2024-07-02 | — |
| 颗粒物 | 8.6 | mg/m³ | 废气排放口 | 2024-07-02 | — |
| 噪声 | 55.6 | dB(A) | 厂界东侧 | 2024-07-02 | — |

`<0.01`、`ND`、`—` 未被转换为 0，符合项目原有规则。

### 5.4 耗时记录

| 阶段 | 耗时 |
| --- | ---: |
| PaddleOCR/PP-StructureV3 初始化（首次） | 6.221 s |
| 包含延迟加载 OCR 模型的首次 PDF 解析 | 53.156 s |
| 独立重复测试：初始化 | 7.781 s |
| 独立重复测试：第 1 次解析 | 50.564 s |
| 独立重复测试：第 2 次解析（模型已预热） | 48.861 s |

首次解析包含了 OCR 检测/识别、表格分类/结构等模型的延迟初始化，因此明显高于预热后的单次解析。

测试输出：

```text
C:\Users\孙强强\AppData\Local\Temp\opencode\pdf_fix_minimal_out\minimal_pdf_result.json
```

---

## 6. PDF 提取结果核对

### 6.1 真实 test_data 文档汇总

使用 `tests\evaluation_support.py` 对 `test_data\` 的 5 份文档执行完整评估：

| 项目 | 结果 |
| --- | ---: |
| 文档数量 | 5（3 Word + 2 PDF） |
| PDF 页面数量 | 每个 PDF 1 页 |
| 标准答案总数 | 21 |
| 实际环保记录数 | 21 |
| 正确匹配 | 21 |
| 漏提取 | 0 |
| 多余提取 | 0 |
| 多候选/歧义 | 0 |
| 重复冲突 | 0 |
| 召回率 | 1.0 |
| 精确率 | 1.0 |
| 位置提示不一致 | 0 |
| 非字面点位行 | 8 |
| 企业数量 | 1 |

### 6.2 两份 PDF 的提取结果

| 文件 | 页数 | 表格 | 表格结构 | 提取记录 | 环保记录 |
| --- | ---: | ---: | --- | ---: | ---: |
| `02_企业废气监测报告.pdf` | 1 | 1 | 5 行 × 4 列，表头 1 行 | 26 | 4 |
| `04_企业年度环境统计报告.pdf` | 1 | 1 | 5 行 × 4 列，表头 1 行 | 26 | 4 |

每个 PDF 的 26 条记录构成：

```text
1 个 ocr_page
24 个 ocr_text
1 个 table
```

PDF 02 关键字段：

| 指标 | 值 | 单位 | 点位 | 时间 | 检出限 |
| --- | --- | --- | --- | --- | --- |
| 颗粒物 | 8.6 | mg/m³ | DA001 废气排放口 | 2026-10-21 | — |
| 二氧化硫 | 空值 | mg/m³ | DA001 废气排放口 | 2026-10-21 | `ND` |
| 氮氧化物 | 35.2 | mg/m³ | DA001 废气排放口 | 2026-10-21 | — |
| 排放速率 | 0.035 | kg/h | DA001 废气排放口 | 2026-10-21 | — |

PDF 04 关键字段：

| 指标 | 值 | 单位 | 时间 |
| --- | --- | --- | --- |
| 年度用水量 | 12500 | m³ | 2026年 |
| 年度用电量 | 286000 | kWh | 2026年 |
| 天然气用量 | 7800 | m³ | 2026年 |
| 污染物产生量 | 4.8 | t/a | 2026年 |

### 6.3 修复前后对比

修复前：

- 本地 PDF 推理在 `PP-DocLayout_plus-L` 处抛出 `NotImplementedError`。
- PDF 无法生成有效表格和 OCR 结果。
- 依赖 PDF 的环保数据、导出和真实数据测试失败。

修复后：

- 同一 PDF 推理成功，`error=None`。
- 表格结构、OCR 文本、页码、bbox 均有效。
- 21 条标准答案仍为 21/21。
- 关键字段、单位、点位、日期、检出限表达与历史验证结果一致。
- Word 文档结果未受影响。

由于修复前 PDF 没有有效输出，无法做逐字段的“修复前内容”对比；本次对比基准为原始标准答案和历史报告中记录的 21/21 结果。

### 6.4 表格结构与文本

- 两份真实 PDF 均识别出 1 个表格，5 行 × 4 列，表头 1 行。
- 表格 bbox 存在，页码为 1。
- OCR 文本包含企业名称、日期、点位、指标、数值、单位等关键内容。
- `needs_review=False`，未产生异常待核实标记。
- 扫描样本 `scanned_special_values.pdf` 为 9 行 × 5 列，`needs_review=True`，符合扫描件的人工复核策略。

---

## 7. 项目一完整测试结果

### 7.1 分组测试

| 分组 | 测试命令范围 | 结果 | 耗时 |
| --- | --- | --- | ---: |
| PDF 相关 | `test_pdf_parser.py`、`test_pdf_table_parsing.py`、`test_paddle_structure.py`、`test_paddle_real.py`、`test_ocr.py`、`pdf_table_special/`、`test_dual_mode.py` | **56 passed，0 failed，0 skipped** | 724.45 s |
| 环保/导出/Word/真实数据 | `test_environmental_*.py`、`test_exporters.py`、`test_word_parser.py`、`test_real_test_data.py` | **43 passed，0 failed，0 skipped** | 399.62 s |

分组测试合计：99 passed，0 failed，0 skipped。

### 7.2 完整测试

执行命令：

```powershell
$env:QT_QPA_PLATFORM="offscreen"
$env:PADDLE_PDX_CACHE_HOME="D:\DocumentAuditSystem\project1_extraction\.paddlex_cache"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"
$env:RUN_PADDLE_STRUCTURE_TESTS="1"
$env:DOC_EXTRACTOR_OUTPUT_DIR="C:\Users\孙强强\AppData\Local\Temp\opencode\pytest_full_out"
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
134 passed, 1 warning in 1414.71s (0:23:34)
```

| 指标 | 修复前（阶段 7） | 修复后 |
| --- | ---: | ---: |
| 收集总数 | 134 | 134 |
| 通过 | 111 | **134** |
| 失败 | 21 | **0** |
| 跳过 | 2 | **0** |

说明：

- 修复前阶段 7 的 2 个跳过项是真实 Paddle 模型测试，因未设置 `RUN_PADDLE_STRUCTURE_TESTS=1` 而跳过。
- 本次完整测试设置了 `RUN_PADDLE_STRUCTURE_TESTS=1`，因此 2 个真实模型测试也被执行并通过，最终为 134 passed、0 skipped。
- 未跳过任何失败测试，未修改测试预期，未删除测试。

---

## 8. Word 回归测试结果

### 8.1 测试结果

- `tests\test_word_parser.py`：5 项全部通过。
- `tests\test_real_test_data.py` 中 Word 相关用例全部通过：
  - Word 正文、标题、表格、企业识别
  - Word 环保数值、单位、日期、单元格位置
  - Word 混合类别
  - 原始值 `ND`、`<0.01`、`—` 不转换为 0
  - 企业归并
  - JSON/Excel 导出
- 完整 134 项测试中未出现 Word 失败。

### 8.2 Word 代码未修改

```text
src\doc_extractor\core\word_parser.py
SHA-256 = 84509FC7AFCCC4E15FA99A172D061F270A55FFC74D002D085F85EB3B6B6E2BB5
最后修改时间 = 2026-10-28 18:35:41
```

该文件早于本次修复时间（2026-11-01 17:52），本次会话未写入该文件。

---

## 9. 原始文件 SHA-256 核验

### 9.1 PDF 测试文件（修复前后一致）

| 文件 | 修复前 SHA-256 | 修复后 SHA-256 | 是否一致 |
| --- | --- | --- | --- |
| `tests\pdf_table_special\samples\scanned_special_values.pdf` | `E95E4C2167F2690F920E2565597A84FF0E14C6AF2F0C3A1BF74409F61FB75622` | 同左 | 是 |
| `tests\pdf_table_special\samples\bordered_special_values.pdf` | `D9C00534547845284B586D4BFB4B3E5B1DC53E48C9A40026B10820A59D8E378D` | 同左 | 是 |
| `tests\pdf_table_special\samples\borderless_native.pdf` | `467D6C92A2E6DA4EF21C8C7B434DD1F7BDE3B9BCA245509E563F2F623FB2D852` | 同左 | 是 |
| `test_data\02_企业废气监测报告.pdf` | `6FCB197671CCCAF37BCB8FC54963BC97F337C0915B4F084CD3DCE5DC610051B6` | 同左 | 是 |
| `test_data\04_企业年度环境统计报告.pdf` | `02985E91562F74B2C6882AB3F954F6A06B9BF6752FA5F87F7F99C22408B56F48` | 同左 | 是 |

### 9.2 test_data 全部文件当前 SHA-256

| 文件 | SHA-256 | 最后修改时间 |
| --- | --- | --- |
| `01_企业废水监测报告.docx` | `3F0B2CE8D75738D062DE285E8FD97FAEF461A2ED4517BAC98678B34C281B62E1` | 2026-10-28 19:00:51 |
| `02_企业废气监测报告.pdf` | `6FCB197671CCCAF37BCB8FC54963BC97F337C0915B4F084CD3DCE5DC610051B6` | 2026-10-28 19:00:51 |
| `03_企业环保管理台账.docx` | `9BAFC2F697EFBA0F2949E6FC12A575FB2501B77A84AB4776F3A0E2B40A561CCA` | 2026-10-28 19:00:51 |
| `04_企业年度环境统计报告.pdf` | `02985E91562F74B2C6882AB3F954F6A06B9BF6752FA5F87F7F99C22408B56F48` | 2026-10-28 19:00:51 |
| `05_企业综合环境数据报告.docx` | `4F8A0E8F40A7F44E91C1FB69140E8188E3C5D15AA3DF84126C3828543AAA1D70` | 2026-10-28 19:00:51 |
| `06_环境数据提取标准答案.xlsx` | `DF7DF90D9D01D650076EF6A62DDEC5750A002A562AE89011C58B0A3C88AAF5C6` | 2026-10-28 19:00:51 |

所有原始测试数据最后修改时间仍为 2026-10-28，早于本次修复，未发生变化。

---

## 10. 项目二、项目三未修改的证据

### 10.1 未执行写操作

本次修复只对以下路径执行了写操作：

```text
src\doc_extractor\core\paddle_structure.py   （源码修改）
docs\PaddleOCR_PDF兼容性诊断报告.md          （上一轮诊断报告）
docs\PaddleOCR_PDF兼容性修复报告.md          （本报告）
C:\Users\孙强强\AppData\Local\Temp\opencode\  （临时脚本、日志、备份、测试输出）
```

未对项目二、项目三执行任何写入、删除、重命名或配置修改。

### 10.2 文件时间戳证据

本次修复会话开始时间约为 **2026-11-01 17:40**。

| 目录 | 最新文件时间 | 是否早于本次会话 |
| --- | --- | --- |
| `D:\DocumentAuditSystem\project2_word_audit\` | 2026-11-01 15:27:49 | 是 |
| `D:\DocumentAuditSystem\project3_cli_workflow\` | 2026-11-01 17:12:57 | 是 |
| `project1_extraction\output\` | 2026-11-01 15:26:48 | 是 |

### 10.3 旧批次和旧审核结果

- 项目一 `output\` 中最新文件为 2026-11-01 15:26:48，早于本次修复。
- 项目二 `output\final_test_typo\` 中最新文件为 2026-11-01 15:27:49，早于本次修复。
- 本次测试输出统一写入临时目录：

```text
C:\Users\孙强强\AppData\Local\Temp\opencode\pytest_pdf_out
C:\Users\孙强强\AppData\Local\Temp\opencode\pytest_env_out
C:\Users\孙强强\AppData\Local\Temp\opencode\pytest_full_out
C:\Users\孙强强\AppData\Local\Temp\opencode\pdf_fix_minimal_out
C:\Users\孙强强\AppData\Local\Temp\opencode\pdf_fix_results_out
```

未覆盖旧批次、旧 JSON/Excel/Markdown 输出或旧审核结果。

### 10.4 未调用云端 API

- `PADDLEOCR_ACCESS_TOKEN` 环境变量检查结果：`NOT_SET`。
- 未读取、打印或写入任何 Token。
- 未执行云端上传、请求或轮询。
- 云端 API 代码 `core\cloud_api_parser.py` 未修改。

---

## 11. 推理性能变化

### 11.1 历史基准（MKLDNN 开启时期）

历史文档 `docs\项目一_本地GPU与云端API整合报告.md` 记录：

| 场景 | 历史耗时 |
| --- | ---: |
| 模型初始化（缓存已存在） | 约 10.83 s |
| 普通文字 PDF（1 页） | 7.72 s |
| 包含表格 PDF（1 页） | 10.37 s |
| 扫描 PDF（1 页） | 8.39 s |
| 多页 PDF（3 页） | 9.89 s |
| 整合后启用真实模型测试（129 项） | 177.28 s |

### 11.2 本次修复后实测

| 场景 | 本次耗时 |
| --- | ---: |
| PaddleOCR/PP-StructureV3 初始化 | 6.221 s / 7.781 s |
| `scanned_special_values.pdf` 首次解析（含模型延迟加载） | 53.156 s / 50.564 s |
| `scanned_special_values.pdf` 预热后解析 | 48.861 s |
| `02_企业废气监测报告.pdf` 预热后解析 | 47.199 s |
| `04_企业年度环境统计报告.pdf` 预热后解析 | 41.720 s |
| 5 份 test_data 文档完整评估 | 114.914 s |
| 项目一完整 134 项测试 | 1414.71 s（23:34） |

### 11.3 性能结论

**关闭 MKLDNN 后 CPU 推理明显变慢。**

- 历史扫描 PDF 为 8.39 s，本次同类扫描样本为 48.9–53.2 s，约 6 倍差距。
- 历史完整测试为 177.28 s（129 项），本次为 1414.71 s（134 项），约 8 倍差距。
- 上述历史数据与本次样本、测试数量、机器状态不完全相同，不能作为严格同条件基准；但性能下降趋势明确。
- 性能下降的直接原因是关闭了 oneDNN/MKLDNN CPU 加速，改用普通 Paddle CPU kernel。
- 本次任务指定的修复方案只要求关闭 MKLDNN，因此未同时尝试其他性能优化参数。

若生产环境对 CPU 推理速度有严格要求，需要在后续单独评估：

1. 等待 PaddlePaddle 修复 oneDNN/PIR 属性转换问题后恢复 MKLDNN。
2. 在独立环境验证 PaddlePaddle 3.2.0（README 记录的历史验证版本）。
3. 评估是否接受当前性能，或增加异步/批处理/缓存策略。

本轮未执行上述后续优化，只完成指定修复。

---

## 12. 是否达到修复验收标准

### 12.1 功能验收

| 验收项 | 结果 |
| --- | --- |
| 原 PIR/MKLDNN 错误消失 | 是 |
| 本地 PDF 推理成功 | 是 |
| 真实测试 PDF 生成有效结果 | 是 |
| 表格结构有效 | 是（真实 PDF 5×4；扫描样本 9×5） |
| OCR 文本有效 | 是 |
| 环保数据有效 | 是（扫描样本 8 条；真实 PDF 各 4 条） |
| 标准答案 21/21 | 是 |
| 召回率/精确率 1.0 | 是 |
| Word 提取不受影响 | 是 |
| 项目一完整 134 项测试 | 134 passed / 0 failed / 0 skipped |
| 依赖版本未变化 | 是 |
| 未调用云端 API | 是 |
| 未修改项目二、项目三 | 是 |
| 未修改原始测试数据 | 是 |

### 12.2 性能验收

任务未给出明确性能阈值。本次修复在功能上达到验收标准，但 CPU 推理性能出现明显下降（见第 11 节）。

因此建议：

- **功能验收：通过。**
- **性能验收：需要用户结合生产要求确认。** 如果当前耗时不可接受，应在后续单独评估性能优化方案，而不是回退到会报错的 MKLDNN 路径。

---

## 13. 仍未确认或需要后续关注的事项

本次修复后没有测试失败，也没有遗留的原错误。但仍有以下事项尚未确认：

1. PaddlePaddle 3.3.1 中触发 `ArrayAttribute<DoubleAttribute>` 的精确 op/属性名。
2. PaddlePaddle 哪个后续版本修复了该 oneDNN/PIR 属性转换问题。
3. PaddlePaddle 3.2.0 在当前 venv 中的实际兼容性和性能（历史文档记录通过，但本轮未降级验证）。
4. GPU 版 PaddlePaddle 对 RTX 5060 Laptop 的支持情况（本轮未安装 GPU 版）。
5. 关闭 MKLDNN 后的长期性能是否满足生产要求。
6. `opencv-python 5.0.0.93` 与 `opencv-contrib-python 4.10.0.84` 的安装冗余是否需要清理（当前运行时 `cv2` 为 4.10.0，未观察到故障）。

---

## 14. 回滚方法

如需回滚本次修复：

1. 删除 `src\doc_extractor\core\paddle_structure.py:604` 的：

```python
"enable_mkldnn": False,
```

2. 或直接恢复备份：

```powershell
Copy-Item `
  "C:\Users\孙强强\AppData\Local\Temp\opencode\backup_project1_20261101_175159\paddle_structure.py.bak" `
  "src\doc_extractor\core\paddle_structure.py"
```

3. 回滚后源码 SHA-256 应恢复为：

```text
0B045F14B6ABC70A90453EF062CB3952F1E20B95B1AACF60485DA1599E2477BB
```

回滚不会影响依赖、模型缓存、测试数据、项目二或项目三。

---

## 15. 最终结论

本次修复按指定方案完成：

- 只在本地 PP-StructureV3 初始化位置增加 `enable_mkldnn=False`。
- 原 `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` 错误不再出现。
- 真实 PDF 可以成功推理并生成有效表格、OCR 文本和环保数据。
- 项目一完整 134 项测试全部通过，0 失败，0 跳过。
- Word 提取、云端 API、依赖版本、原始测试数据均未受影响。
- 项目二、项目三未被修改。

**功能修复成功。性能明显下降，需用户确认是否接受；本轮未进行进一步性能优化，也未进入其他功能开发。**
