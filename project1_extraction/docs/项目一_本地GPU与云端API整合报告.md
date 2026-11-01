# 项目一_本地GPU与云端API整合报告

## 1. 整合前后架构

### 1.1 整合前

```text
PDF
└─ PaddleOCR PP-StructureV3
   └─ 本地 PaddleOCR 单引擎解析
```

项目一已经完成 PaddleOCR 单引擎版本，但只有本地推理路径，界面没有解析模式选择。

### 1.2 整合后

```text
PDF 统一解析入口 parse_pdf(mode=...)
├─ local_gpu
│  └─ 本地 PaddleOCR PP-StructureV3
│     ├─ PyMuPDF 仅渲染页面图像
│     └─ 本地 PaddleOCR 模型推理
└─ cloud_api
   └─ PaddleOCR 官方云端 API
      └─ PP-StructureV3
```

- 两种模式都使用 PP-StructureV3。
- 两种模式统一返回 `DocumentResult`、`ExtractionRecord`、`TableData` 和 `EnvironmentalRecord`。
- 环境数据提取模块不区分底层解析方式。
- Word 继续使用 `python-docx`。
- 不使用 RapidOCR。
- 不自动切换本地/云端模式。
- 云端模式在提取前必须由用户确认上传。

## 2. 实际修改的文件

### 2.1 新增

| 文件 | 作用 |
| --- | --- |
| `src/doc_extractor/core/cloud_api_parser.py` | PaddleOCR 官方云端 API 客户端封装、PP-StructureV3 调用、Markdown/结构化结果转换、Token 缺失/网络/超时错误处理 |
| `src/doc_extractor/core/device_status.py` | 本地 GPU/CPU 状态检测 |
| `tests/dual_mode_support.py` | 云端 API 模拟客户端、页面与表格结果样本 |
| `tests/test_dual_mode.py` | 双模式、统一格式、Token、断网、超时、JSON/Excel、GPU 状态测试 |
| `tests/test_dual_mode_ui.py` | 模式切换、上传确认、Token 缺失阻止启动、GPU 提示测试 |

### 2.2 修改

| 文件 | 修改 |
| --- | --- |
| `core/pdf_parser.py` | 增加 `local_gpu` / `cloud_api` 统一入口与模式分发 |
| `core/paddle_pdf_parser.py` | 本地模式增加 `extraction_mode=local_gpu`、设备状态、表格模式元数据 |
| `core/paddle_structure.py` | 增加模型是否已加载状态查询 |
| `core/extractor.py` | 向下传递解析模式与云端客户端参数 |
| `core/environmental_pipeline.py` | 批量提取支持双模式 |
| `core/environmental_models.py` | 环境记录新增 `extraction_engine`、`extraction_mode` |
| `core/environmental_common.py` | 环境记录填充提取引擎/模式；表格 bbox 过滤兼容单元格范围 |
| `core/exporters.py` | JSON/Excel 输出提取引擎与解析模式；Excel 表格/环境数据新增列 |
| `ui/worker.py` | 后台线程支持本地/云端模式 |
| `ui/main_window.py` | 本地/云端模式单选框、GPU/API/模型状态、上传确认、错误提示 |
| `pyproject.toml` / `requirements.txt` | 增加 `requests`；PaddleOCR/PaddlePaddle 保持主依赖 |
| `README.md` | 双模式、Token 安全配置、启动和使用说明 |

### 2.3 保留但未使用

停用的历史 RapidOCR 适配器 `core/ocr.py` 已在最终清理阶段删除；PDF 解析运行时不存在 RapidOCR 路径。

## 3. 依赖变化

- 未复制独立 API 测试目录的 `.venv`。
- 项目 `.venv` 已包含 PaddleOCR 3.7.0 自带的官方 `_api_client`。
- 项目 `.venv` 已包含 `requests`，本次将其加入显式依赖。
- 未引入额外第三方云端 SDK。
- 未恢复 RapidOCR 依赖。

实际版本：

| 组件 | 版本/状态 |
| --- | --- |
| Python | 3.12.10 |
| PaddlePaddle | 3.2.0 |
| PaddleOCR | 3.7.0 |
| PyMuPDF | 2.0 |
| PySide6 | 6.12.0 |
| requests | 2.34.2 |
| Paddle 编译 | CPU |
| CUDA | 不可用，设备数 0 |
| 实际设备 | `cpu` |

## 4. 本地GPU验证结果

检查结果：

- PaddlePaddle 为 **CPU 版本**。
- `paddle.is_compiled_with_cuda()`：`False`。
- CUDA 设备数：`0`。
- `paddle.get_device()`：`cpu`。
- 当前机器未检测到可用 GPU。

因此：

- **不能声称 GPU 推理已验证或已启用。**
- 界面在本地模式明确显示“GPU 不可用：当前为 Paddle CPU 版”。
- 本地模式实际使用 CPU 推理，以保证现有本地功能可运行。
- 本地模式不会自动切换到云端。
- 真实 GPU 推理仍需在安装 GPU 版 PaddlePaddle 且有 CUDA 设备的机器上重新验证。

本地性能（CPU，模型已缓存）：

| 场景 | 页数 | 耗时 |
| --- | ---: | ---: |
| 普通文字 PDF | 1 | 7.72s |
| 包含表格 PDF | 1 | 10.37s |
| 扫描 PDF | 1 | 8.39s |
| 多页 PDF | 3 | 9.89s |

模型初始化（缓存已存在）约 10.83s；初始化后 RSS 约 1.44 GB，连续解析多份文档后约 3.32 GB。

## 5. 云端API验证结果

### 5.1 独立测试目录检查

检查 `D:\PaddleOCR_API_Test`：

- 目录中存在独立 `.venv`。
- 未发现保存的 API 测试脚本、JSONL 结果或测试报告。
- 该 `.venv` 中 PaddleOCR 3.7.0 包含官方 `_api_client`。
- 项目 `.venv` 同样包含官方 `_api_client` 与 `requests`。

### 5.2 实际使用的官方 API

使用 PaddleOCR 官方客户端：

```python
from paddleocr._api_client.client import PaddleOCRClient
from paddleocr._api_client.models import Model, PPStructureV3Options
```

云端参数：

- 模型：`PP-StructureV3`
- `use_table_recognition=True`
- 关闭方向分类、去畸变、印章、公式、图表、区域检测（与本地配置保持一致）
- Token：只从 `PADDLEOCR_ACCESS_TOKEN` 环境变量读取

### 5.3 真实 API 验证状态

当前运行环境检查结果：

- 进程环境变量：`PADDLEOCR_ACCESS_TOKEN` 未设置。
- Windows 用户环境变量：未设置。
- Windows 机器环境变量：未设置。

因此：

- **未能执行真实云端 API 请求。**
- 没有上传任何测试 PDF。
- 未测量真实云端 API 准确率或网络延迟。
- 已验证官方客户端类、`PPStructureV3Options` 和 `Model.PP_STRUCTURE_V3` 可以正常导入。
- 已验证在提供假 Token 时客户端对象可以创建（不发起网络请求）。

### 5.4 模拟云端 API 测试结果

使用注入的模拟官方客户端完成：

| 测试 | 结果 |
| --- | --- |
| 云端单页解析 | 通过 |
| 云端多页解析 | 通过 |
| 云端表格转换 | 通过 |
| 云端 Markdown 表格回退 | 通过 |
| Token 缺失 | 返回明确错误，不调用本地 OCR |
| 断网 | 返回明确错误，不回退本地 |
| 请求超时 | 返回明确错误 |
| Token 不写入错误/元数据/日志 | 通过 |
| JSON 统一字段 | 通过 |
| Excel 统一字段 | 通过 |
| 云端模式不初始化本地模型 | 通过 |

模拟云端合成表格结果：表格 5×8，环境数据 **10/10** 关联正确。

> 该 10/10 是模拟官方返回结果的数据转换准确率，不是真实云端 API 准确率。

## 6. 模式切换测试

PySide6 界面已增加：

- `本地 GPU（PaddleOCR）`
- `云端 API（PaddleOCR）`

验证结果：

- 模式由用户主动选择，不会自动切换。
- 选择云端模式后显示“PDF 将上传到远程服务”的提示。
- 点击开始提取前再次弹出上传确认。
- 用户选择“否”时不会启动云端任务。
- 未配置 Token 时阻止云端任务启动，并给出明确错误。
- 未配置 Token 时不会自动切换到本地模式。
- 本地模式 GPU 不可用时显示警告，但仍使用本地 CPU，不切换云端。
- 模式切换期间任务按钮和模式单选框会禁用，避免运行中切换。
- 状态区显示当前模式、GPU 状态、API Token 状态、模型加载状态、最近调用状态。
- 错误信息显示在现有警告区和状态栏。
- OCR/云端解析在后台线程执行，离屏 UI 测试验证事件循环可继续处理定时器事件。

## 7. 环境数据准确率

### 7.1 本地模式（真实 PaddleOCR）

使用原始 `test_data/` 和原始标准答案，未修改标准答案：

| 指标 | 结果 |
| --- | ---: |
| 标准答案总数 | 21 |
| 实际提取数 | 21 |
| 正确匹配 | 21 |
| 漏提取 | 0 |
| 多余提取 | 0 |
| 重复匹配 | 0 |
| 召回率 | 1.0 |
| 精确率 | 1.0 |
| 来源位置提示一致 | 21 |

### 7.2 云端模式

- 真实云端 API：**未执行**（Token 未配置）。
- 模拟云端返回：合成表格环境数据 **10/10**。
- 云端转换后的 JSON/Excel 字段与本地模式一致，仅 `extraction_mode` 不同。
- 两种模式的环境记录都包含：
  - `extraction_engine = "PaddleOCR"`
  - `extraction_mode = "local_gpu"` 或 `"cloud_api"`
  - 来源文件、页码、表格行列、坐标、待核实标记

**不能将模拟云端的 10/10 当作真实云端 API 准确率。**

## 8. 统一数据格式

环境记录新增字段：

- `extraction_engine`：固定 `PaddleOCR`
- `extraction_mode`：`local_gpu` / `cloud_api`

保留字段：

- 企业名称
- 环境指标
- 监测点位
- 监测日期
- 数值
- 单位
- 来源文件
- PDF 页码
- 表格行列
- 原文坐标
- 待人工核实标记

云端结果转换：

1. 优先使用官方返回的 `prunedResult`。
2. 兼容 snake_case / camelCase 键名。
3. 使用现有 PP-StructureV3 表格/OCR 结果转换逻辑。
4. `prunedResult` 不可用时，解析 Markdown 表格作为回退。
5. Markdown 表格无坐标时标记 `cloud_markdown_table`。
6. 云端结果缺少图像坐标尺寸时标记 `cloud_coordinates_unknown`。
7. 不丢失企业、页码、行列、原文等字段。

## 9. 测试汇总

| 运行方式 | 收集 | 通过 | 失败 | 跳过 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 整合前基线 | 108 | 106 | 0 | 2 | 156.04s |
| 整合后默认 | 129 | 127 | 0 | 2 | 154.89s |
| 整合后启用真实模型 | 129 | 129 | 0 | 0 | 177.28s |

新增双模式测试：**20 项全部通过**。

真实 GPU 和真实云端 API 未执行；已明确与模拟测试区分。

## 10. 已知问题

1. 当前机器没有 GPU，本地模式实际为 CPU；真实 GPU 推理未验证。
2. 当前没有 `PADDLEOCR_ACCESS_TOKEN`，真实云端 API 未验证。
3. 独立 API 测试目录中没有保存的测试脚本或结果文件，无法复用其具体测试记录。
4. 云端真实返回格式可能与模拟样本存在差异；已完成 `prunedResult` 与 Markdown 两条转换路径，但仍需用真实 Token 验证。
5. 云端模式会上传 PDF 到远程服务，存在数据合规与配额成本，必须人工确认。
6. 复杂多级表头/合并单元格的列错位问题仍然存在。
7. 无边框表格当前模型仍可能无法检出。
8. 本地模型内存占用较高。
9. 项目目录不是 Git 仓库，未创建 Git 提交检查点；本次未删除或覆盖原有功能代码。

## 11. 软件启动方法

```powershell
cd D:\DocumentAuditSystem\project1_extraction
.\.venv\Scripts\python.exe -m doc_extractor
```

使用云端模式时，需要先安全配置 Token。

仅当前终端会话有效：

```powershell
$env:PADDLEOCR_ACCESS_TOKEN = "你的 Token"
.\.venv\Scripts\python.exe -m doc_extractor
```

让以后启动的软件也能读取：

```powershell
setx PADDLEOCR_ACCESS_TOKEN "你的 Token"
```

设置后重新打开终端/软件。程序不会打印、记录或显示 Token；请勿把 Token 写入项目文件或提交到 Git。

## 12. 结论

- 项目一已实现本地 PaddleOCR 与云端 PaddleOCR API 的统一解析接口。
- 两种模式都使用 PP-StructureV3，并输出统一 JSON/Excel/环境数据结构。
- 原有 Word/PDF 提取、环境指标、来源定位、导出和 PySide6 流程保留。
- 本地模式真实 21 条标准答案仍为 **21/21**。
- 云端模式完成模拟客户端验证；真实云端 API 因 Token 未配置而未执行。
- 当前无 GPU，未声称 GPU 已验证；本地模式在界面明确提示 GPU 不可用并使用 CPU。
- 未使用 RapidOCR，未自动切换模式，未泄露 Token，未修改其他项目。
