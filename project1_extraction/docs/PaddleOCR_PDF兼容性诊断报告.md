# PaddleOCR PDF 兼容性诊断报告

- 诊断时间：2026-11-01
- 诊断对象：`D:\DocumentAuditSystem\project1_extraction`
- 诊断范围：只读检查 + 最小化本地推理复现
- 本轮未修改任何项目源码、配置、依赖或模型，未调用云端 API，未读取或输出 Token。

## 0. 结论摘要

**错误根因已确认（高置信度）**：

项目一 PDF 解析失败发生在 **PaddlePaddle 3.3.1 CPU 版的 PIR 新执行器 + oneDNN/MKLDNN 推理路径**，而不是 PaddleOCR 参数、PP-StructureV3 调用方式或项目一业务代码。

实际失败点在 **PP-StructureV3 的第一个模型 `PP-DocLayout_plus-L`（版面检测）**：

```text
PaddleStaticRunner.__call__
  -> paddle_inference.Predictor.run()
  -> paddle/fluid/framework/new_executor/instruction/onednn/onednn_instruction.cc:118
  -> ConvertPirAttribute2RuntimeAttribute not support
     [pir::ArrayAttribute<pir::DoubleAttribute>]
```

PaddleX 在 CPU 上默认选择 `run_mode=mkldnn`，并为 `PP-DocLayout_plus-L` 启用 `enable_new_ir=True`。两者叠加触发了该底层缺陷。

**已验证修复方向**：

1. 构造时传入 `enable_mkldnn=False`：实测 PDF 推理成功（1 个表格、9 行 5 列、55 行 OCR 文本）。
2. 在导入 PaddleOCR/PaddleX 前设置 `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False`：实测同样成功。

两种方式都只关闭 CPU oneDNN 加速，不改变模型、不降级依赖、不影响 Word 提取。

**尚未确认**：

- 触发错误的精确 Paddle op 名称与属性名（只能确认是 oneDNN 指令属性转换层）。
- PaddlePaddle 3.3.1 的哪个后续补丁版本修复了该问题。
- 将 PaddlePaddle 降级到 README 记录的历史验证版本 3.2.0 在当前环境中的实际结果（本轮禁止安装/降级，未验证）。
- GPU 版 PaddlePaddle 在本机 RTX 5060 Laptop（Blackwell）上的可用性。

---

## 1. Python 环境信息

| 项目 | 值 |
| --- | --- |
| 操作系统 | Windows 11 家庭中文版 10.0.26100（Build 26100，64 位） |
| CPU | AMD Ryzen 9 8940HX，16 核 / 32 线程 |
| 内存 | 33,520,316,416 字节（约 31.2 GiB） |
| Python 版本 | 3.12.10 |
| Python 可执行文件 | `D:\DocumentAuditSystem\project1_extraction\.venv\Scripts\python.exe` |
| 虚拟环境路径 | `D:\DocumentAuditSystem\project1_extraction\.venv` |
| 虚拟环境基础解释器 | `C:\Users\孙强强\AppData\Local\Programs\Python\Python312\python.exe` |
| `sys.prefix` | `D:\DocumentAuditSystem\project1_extraction\.venv` |
| `sys.base_prefix` | `C:\Users\孙强强\AppData\Local\Programs\Python\Python312` |
| 是否使用系统 Python | 否 |
| pip 版本 | 26.2.2 |
| 平台标识 | `Windows-11-10.0.26100-SP0` |
| 架构 | 64bit / AMD64 |

结论：项目一实际使用自己的 `.venv`，未误用系统 Python 或其他项目环境。

---

## 2. PaddlePaddle 版本

| 项目 | 值 |
| --- | --- |
| `paddlepaddle` | **3.3.1** |
| `paddlepaddle-gpu` | 未安装 |
| `paddle.__version__` | 3.3.1 |
| `paddle.device.get_device()` | `cpu` |
| `paddle.device.is_compiled_with_cuda()` | `False` |
| `paddle.device.cuda.device_count()` | 0 |
| `paddle.get_cudnn_version()` | `None` |
| oneDNN 版本（运行日志） | oneDNN v3.6.2 |
| Paddle 默认 PIR 标志 | `FLAGS_enable_pir_api=True` |
| Paddle 默认 PIR 执行器标志 | `FLAGS_enable_pir_in_executor=True` |

说明：当前安装的是 **CPU 版 PaddlePaddle**，不是 GPU 版。即使机器上有 NVIDIA GPU，Paddle 也不会使用。

---

## 3. PaddleOCR 版本

| 项目 | 值 |
| --- | --- |
| `paddleocr` | **3.7.0** |
| 实际导入 | `from paddleocr import PPStructureV3` |
| PP-StructureV3 实现 | `paddleocr\_pipelines\pp_structurev3.py` |
| PaddleOCR 依赖声明 | `paddlex[ocr-core]>=3.7.0,<3.8.0` |

PaddleOCR 3.7.0 的版本约束与已安装 PaddleX 3.7.2 匹配，未发现 PaddleOCR/PaddleX 版本越界。

---

## 4. PaddleX 版本

| 项目 | 值 |
| --- | --- |
| `paddlex` | **3.7.2** |
| PP-StructureV3 实际流水线 | `paddlex.inference.pipelines.layout_parsing.pipeline_v2.LayoutParsingPipelineV2` |
| 内部实现 | `_LayoutParsingPipelineV2` |
| 推理 Runner | `PaddleStaticRunner`（Paddle Inference 静态图） |

运行时实际读取到的版面检测模型配置：

```text
layout_det_model = PP-DocLayout_plus-L
runner = PaddleStaticRunner
device_type = cpu
run_mode = mkldnn
enable_new_ir = True
```

这是本次错误的关键运行时证据。

---

## 5. CUDA / GPU 信息

| 项目 | 值 |
| --- | --- |
| NVIDIA 驱动 | 616.56 |
| CUDA UMD 版本 | 13.4 |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU，8151 MiB |
| 其他显示设备 | AMD Radeon 610M；ToDesk Virtual Display Adapter |
| `nvcc` | 未在 PATH 中找到 |
| Paddle CUDA 编译 | `False` |
| Paddle 可见 GPU 数 | 0 |
| cuDNN 信息 | 不可读取（`paddle.get_cudnn_version()` 返回 `None`） |
| 实际推理设备 | `cpu` |

结论：

- 机器存在 NVIDIA GPU，但当前 PaddlePaddle 是 CPU 版，无法使用 CUDA。
- 因此本次失败与“CUDA 驱动/CUDA 运行时/cuDNN”无关。
- 项目代码中的 `local_gpu` 只是模式名称，实际设备是 CPU；README 和 `device_status.py` 已能正确提示 GPU 不可用。

---

## 6. 相关依赖版本

| 依赖 | 已安装版本 | 说明 |
| --- | --- | --- |
| paddlepaddle | 3.3.1 | CPU 版 |
| paddlepaddle-gpu | 未安装 | 无重复 Paddle 安装 |
| paddleocr | 3.7.0 | 与 PaddleX 3.7.2 匹配 |
| paddlex | 3.7.2 | PP-StructureV3 实际执行层 |
| numpy | 2.3.5 | 满足 PaddleX `>=1.24,<2.4` |
| opencv-python | 5.0.0.93 | 元数据存在 |
| opencv-contrib-python | 4.10.0.84 | PaddleX 固定要求该版本 |
| 运行时 `cv2.__version__` | 4.10.0 | 实际加载的是 4.10.0 |
| protobuf | 7.36.2 | 满足 PaddlePaddle `>=3.20.2` |
| shapely | 2.2.0 | — |
| pyclipper | 1.4.0 | — |
| PyMuPDF（发行名 `pymupdf`） | 2.0 | 用于 PDF 页面渲染 |
| Pillow | 13.0.0 | — |
| scipy | 1.18.1 | — |
| pandas | 3.1.0 | — |
| modelscope | 1.40.2 | — |
| onnxruntime | 1.31.1 | 未参与当前 PDF 解析 |
| rapidocr-onnxruntime | 1.4.4 | 已安装但项目 PDF 路径不使用 |

依赖健康检查：

```text
pip check
No broken requirements found.
```

发现的环境整洁性问题（**不是本次报错原因**）：

1. `opencv-python 5.0.0.93` 与 `opencv-contrib-python 4.10.0.84` 同时存在。
   - 两个发行包共享 `cv2` 目录，后安装的 `opencv-contrib-python 4.10.0.84` 覆盖了运行时文件。
   - 当前 `cv2.__version__` 为 4.10.0，符合 PaddleX 的要求。
   - 残留的 `opencv-python 5.0.0.93` 元数据和旧 DLL 属于安装冗余，未观察到当前功能受其影响。
2. `paddlepaddle-gpu` 未安装，不存在 CPU/GPU 双包冲突。
3. 锁文件 `uv.lock` 与当前环境一致（paddlepaddle 3.3.1、paddleocr 3.7.0、paddlex 3.7.2），但与 README/历史报告记录的 **PaddlePaddle 3.2.0** 不一致。
   - `README.md` 第 99 行记录“当前验证版本：PaddleOCR 3.7.0、PaddlePaddle 3.2.0”。
   - `docs\项目一_本地GPU与云端API整合报告.md` 记录 PaddlePaddle 3.2.0，并记录当时 129 项测试全部通过。
   - 当前环境已变为 3.3.1，且 PDF 解析失败。

---

## 7. PDF 解析调用链

### 7.1 项目内调用链

```text
parse_pdf(path, mode="local_gpu")
  core/pdf_parser.py:38
    -> parse_pdf_local(...)
       core/paddle_pdf_parser.py:208
         -> get_paddle_structure_parser()
            core/paddle_structure.py:731
              -> PaddleStructureParser()
                 core/paddle_structure.py:579
                   ensure_paddle_cache_dir()
                   from paddleocr import PPStructureV3
                   PPStructureV3(
                       use_doc_orientation_classify=False,
                       use_doc_unwarping=False,
                       use_textline_orientation=False,
                       use_seal_recognition=False,
                       use_formula_recognition=False,
                       use_chart_recognition=False,
                       use_region_detection=False,
                       use_table_recognition=True,
                   )
         -> PyMuPdfRenderer.render_pages(...)
         -> parser.parse_page(page.image, ...)
            core/paddle_structure.py:613
              -> PPStructureV3.predict(...)
                 core/paddle_structure.py:625
```

### 7.2 PaddleOCR / PaddleX 内部调用链

```text
PPStructureV3.predict
  paddleocr\_pipelines\pp_structurev3.py:261
    -> LayoutParsingPipelineV2.predict
       paddlex\inference\pipelines\layout_parsing\pipeline_v2.py:1059
         -> layout_det_model（PP-DocLayout_plus-L）
            paddlex\inference\models\object_detection\predictor.py:239
              -> PaddleStaticRunner.__call__
                 paddlex\inference\models\runners\paddle_static\runner.py:297
                   -> PaddleRunnerChainLegacy.__call__
                      runner.py:265
                        -> paddle_inference.Predictor.run()
                           -> C++ oneDNN instruction
```

### 7.3 实际推理模式

| 项目 | 实际值 | 来源 |
| --- | --- | --- |
| 推理引擎 | Paddle Inference 静态图 | PaddleX `PaddleStaticRunner` |
| 设备 | CPU | Paddle 为 CPU 版 |
| PaddleX `run_mode` | `mkldnn` | CPU 默认 + `DEFAULT_ENABLE_MKLDNN=True` |
| 新 IR / PIR | 启用 | `enable_new_ir=True` |
| 新执行器 | 启用 | `config.enable_new_executor()` |
| oneDNN | 启用 | `run_mode=mkldnn` |
| 首个执行模型 | `PP-DocLayout_plus-L` | 版面检测 |
| 模型文件 | `inference.json` + `inference.pdiparams` | 已缓存且可加载 |

PaddleX 默认值的源码依据：

- `paddlex\inference\models\runners\paddle_static\config\pp_option.py:32-44`
  - CPU 且 MKLDNN 可用、模型不在 `MKLDNN_BLOCKLIST` 时，`run_mode` 默认为 `mkldnn`。
- `pp_option.py:140`
  - `enable_new_ir` 默认 `True`，仅 `NEWIR_BLOCKLIST` 中的模型关闭。
- `paddlex\inference\models\runners\paddle_static\config\blocklists.py`
  - `PP-DocLayout_plus-L` 不在 `MKLDNN_BLOCKLIST`，也不在 `NEWIR_BLOCKLIST`。
- `paddleocr\_constants.py`
  - `DEFAULT_ENABLE_MKLDNN = True`。

项目一没有显式设置 `device`、`enable_mkldnn` 或 `engine_config`，因此完全采用上述默认值。

---

## 8. 完整异常堆栈

以下为使用项目一真实代码路径、真实缓存模型、真实测试 PDF 复现得到的完整堆栈（未调用云端 API）：

```text
Traceback (most recent call last):
  File "D:\DocumentAuditSystem\project1_extraction\src\doc_extractor\core\paddle_structure.py", line 625, in parse_page
    results = self._pipeline.predict(
              ^^^^^^^^^^^^^^^^^^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddleocr\_pipelines\pp_structurev3.py", line 261, in predict
    return list(
           ^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\pipelines\_parallel.py", line 161, in predict
    yield from self._pipeline.predict(
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\pipelines\layout_parsing\pipeline_v2.py", line 1059, in predict
    layout_det_results = list(
                         ^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\models\predictors\base_predictor.py", line 117, in __call__
    yield from self.apply(input, **kwargs)
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\models\predictors\base_predictor.py", line 140, in apply
    pred = self.process(batch_data, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\models\object_detection\predictor.py", line 239, in process
    batch_preds = self.runner(batch_inputs)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\models\runners\paddle_static\runner.py", line 297, in __call__
    pred = self.infer(x)
           ^^^^^^^^^^^^^
  File "D:\DocumentAuditSystem\project1_extraction\.venv\Lib\site-packages\paddlex\inference\models\runners\paddle_static\runner.py", line 265, in __call__
    self.predictor.run()
NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]  (at ..\paddle\fluid\framework\new_executor\instruction\onednn\onednn_instruction.cc:118)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "C:\Users\孙强强\AppData\Local\Temp\opencode\diag_paddle_pdf2.py", line 72, in <module>
    result = parser.parse_page(
  File "D:\DocumentAuditSystem\project1_extraction\src\doc_extractor\core\paddle_structure.py", line 637, in parse_page
    raise PaddleStructureError(
doc_extractor.core.paddle_structure.PaddleStructureError: PP-StructureV3 推理失败：NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]  (at ..\paddle\fluid\framework\new_executor\instruction\onednn\onednn_instruction.cc:118)
```

补充观察：

- `PaddleStructureParser()` 初始化阶段成功：8 个模型均从缓存加载并完成 predictor 创建。
- 错误发生在第一次 `predict()`，即 `PP-DocLayout_plus-L` 执行时。
- 因此不是模型缺失、模型文件损坏、下载失败或缓存路径错误。
- 项目一的 `PaddleStructureError` 只是对底层异常的外层包装，不改变错误性质。

---

## 9. 错误发生层级分析

逐层判断：

| 层级 | 判断 | 依据 |
| --- | --- | --- |
| 项目一调用方式 | 非直接原因 | 调用链正确；初始化成功；仅使用默认 device/mkldnn 配置 |
| PaddleOCR | 非直接原因 | PPStructureV3 正常分派到 PaddleX；参数合法 |
| PaddleX | 触发条件所在层 | 默认选择 `run_mode=mkldnn` + `enable_new_ir=True` |
| PP-StructureV3 模型/结果转换 | 非原因 | 错误发生在第一个模型推理，尚未进入结果后处理 |
| 模型文件/缓存 | 非原因 | 模型文件存在且可创建 predictor；关闭 oneDNN 后同一模型成功 |
| PaddlePaddle 推理后端 | **直接原因层** | 异常来自 `onednn_instruction.cc:118` 的 PIR 属性转换 |
| CUDA/cuDNN | 无关 | Paddle 为 CPU 版，未使用 CUDA |

精确层级：

```text
PaddlePaddle 3.3.1 C++ 推理运行时
  └─ PIR 新执行器（new_executor）
     └─ oneDNN instruction
        └─ ConvertPirAttribute2RuntimeAttribute
           └─ 不支持 pir::ArrayAttribute<pir::DoubleAttribute>
```

**不是** PaddleOCR 抛出的业务错误，也**不是** PaddleX Python 层的结果解析错误；PaddleX 只是把 Paddle 的 `NotImplementedError` 原样向上传递。

---

## 10. 最可能的原因及证据

### 10.1 主要原因

PaddlePaddle 3.3.1 CPU 版在 **PIR 新执行器 + oneDNN/MKLDNN** 路径上，对 `PP-DocLayout_plus-L` 推理模型中的某个属性执行 `ConvertPirAttribute2RuntimeAttribute` 时，不支持 `ArrayAttribute<DoubleAttribute>`，直接抛出 `NotImplementedError`。

PaddleX 在 CPU 上默认启用 MKLDNN 和新 IR，因此该缺陷在项目一默认配置下必然触发。

### 10.2 证据

**证据 1：真实堆栈指向 oneDNN 指令层**

```text
onednn_instruction.cc:118
ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]
```

**证据 2：运行时配置确认 `mkldnn` + 新 IR**

对项目一实际创建的 PaddleX 流水线做只读内省，得到：

```text
layout_det_model = PP-DocLayout_plus-L
runner = PaddleStaticRunner
device_type = cpu
run_mode = mkldnn
enable_new_ir = True
```

**证据 3：关闭 oneDNN 后同一 PDF、同一模型推理成功**

使用项目一现有测试 PDF：

```text
tests\pdf_table_special\samples\scanned_special_values.pdf
SHA-256 = E95E4C2167F2690F920E2565597A84FF0E14C6AF2F0C3A1BF74409F61FB75622
```

以 `PaddleStructureParser(enable_mkldnn=False)` 运行：

```text
init_parser_ok
predict_ok
tables = 1
lines = 55
table rows/cols = 9 5
warnings = []
```

**证据 4：不改代码、仅改环境变量也能复现修复效果**

在导入 PaddleOCR/PaddleX 前设置：

```text
PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=False
```

结果同样为：

```text
predict_ok
tables = 1
lines = 55
```

**证据 5：版本漂移**

- README 与历史整合报告记录已验证版本为 PaddlePaddle **3.2.0**，当时 129 项测试全部通过。
- 当前实际版本为 PaddlePaddle **3.3.1**。
- 当前测试收集数为 134，失败 21，失败集中在 PDF 解析及依赖 PDF 的环保数据、导出和真实数据测试。
- 版本变化与故障出现时间一致，指向 3.3.1 的运行时回归。

**证据 6：模型缓存完整**

- `PP-DocLayout_plus-L` 等模型位于 `D:\DocumentAuditSystem\project1_extraction\.paddlex_cache\official_models`。
- 模型文件完整（`inference.json`、`inference.pdiparams` 等），本轮诊断未修改模型文件。
- 关闭 oneDNN 后模型可正常推理，排除模型损坏。

**证据 7：模型属性中存在 Double 数组候选**

对 `PP-DocLayout_plus-L\inference.json` 只读分析，发现：

- 2 个 `assign_value_` 节点的 `values` 属性是 `a_f64` 数组（对应 DoubleAttribute）。
- 2 个 `nearest_interp` 节点的 `scale` 属性是 `a_f32` 数组。

这与错误中的 `ArrayAttribute<DoubleAttribute>` 相符，但**具体由哪个 op/属性触发尚未确认**，需要 Paddle 内部调试符号或上游修复记录才能最终定位。

### 10.3 次要发现（不是本次 21 个失败的原因）

诊断过程中发现一个独立的缓存路径风险：

- PaddleX 的 `CACHE_DIR` 在 `paddlex\utils\cache.py:29` 导入时一次性读取 `PADDLE_PDX_CACHE_HOME`。
- 如果先导入 `paddlex`/`paddleocr`，再调用项目一的 `ensure_paddle_cache_dir()`，环境变量将不再生效，模型会从 `C:\Users\孙强强\.paddlex`（含中文路径）加载。
- 首次诊断脚本正是这种导入顺序，结果出现另一个错误：

```text
RuntimeError: [json.exception.parse_error.101] parse error at line 1, column 1:
attempting to parse an empty input; check that your input string or stream
contains the expected JSON
```

- 项目一正常代码路径是：`ensure_paddle_cache_dir()` → 再导入 `paddleocr`，因此正常使用 ASCII 缓存目录 `D:\...\project1_extraction\.paddlex_cache`，未触发该问题。
- 该问题说明：**后续任何修改都必须保证在导入 PaddleX 之前完成缓存目录设置**。

---

## 11. 修复方案

### 方案 A（推荐，已验证）：关闭 CPU oneDNN/MKLDNN

#### A1. 代码方式

在 `src\doc_extractor\core\paddle_structure.py` 的 `PaddleStructureParser.__init__` 中，为 `PPStructureV3` 增加：

```python
options: dict[str, Any] = {
    ...
    "use_table_recognition": True,
    "enable_mkldnn": False,
}
```

即最终调用：

```python
self._pipeline = PPStructureV3(**options)
```

本轮已用等价方式 `PaddleStructureParser(enable_mkldnn=False)` 实测成功。

#### A2. 环境变量方式（不改源码）

在启动应用或运行 pytest 前设置：

```powershell
$env:PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT = "False"
```

必须保证该变量在导入 PaddleOCR/PaddleX **之前**生效。

本轮已实测成功。也可以在 `run_project1.bat` 中设置，但该文件属于项目配置/启动脚本，本轮未修改。

#### A1 与 A2 的取舍

| 方式 | 优点 | 缺点 |
| --- | --- | --- |
| A1 代码传入 `enable_mkldnn=False` | 对应用和 pytest 都生效；修复点集中；可随代码审查 | 需要改 1 行源码 |
| A2 环境变量 | 不改源码；可快速回滚 | 依赖启动方式；pytest/IDE/其他入口需分别设置；影响同进程所有 PaddleX 模型 |

推荐 **A1** 作为最终修复，A2 作为验证和临时规避手段。

### 方案 B（备选，未验证）：降级 PaddlePaddle 到 3.2.0

README 和历史报告记录 3.2.0 曾验证通过，因此可考虑：

```text
paddlepaddle 3.3.1 -> 3.2.0
```

但本轮禁止安装/降级，**该方案在当前环境未验证**。同时 `uv.lock` 当前锁定 3.3.1，降级需要同步修改依赖锁定文件，风险高于方案 A。

### 方案 C（不推荐作为首选）：升级到修复该缺陷的 PaddlePaddle 版本

如果 PaddlePaddle 后续版本修复了 oneDNN 对 `ArrayAttribute<DoubleAttribute>` 的转换，可升级解决。但目前：

- 未确认具体修复版本。
- 本轮禁止安装/升级。
- 不能保证新版本不会引入其他兼容性问题。

因此仅作为后续跟踪项。

### 方案 D（不推荐作为首选）：安装 GPU 版 PaddlePaddle

GPU 路径的 `run_mode` 默认为 `paddle`，不走 oneDNN instruction，理论上可绕过该错误。但：

- 当前机器是 RTX 5060 Laptop（Blackwell），对 CUDA/驱动/Paddle GPU wheel 要求较高。
- 未验证当前 PaddlePaddle GPU wheel 是否支持该 GPU。
- 下载体积大、部署复杂、需要重新验证。
- 本轮禁止安装。

仅在有明确 GPU 部署需求时评估。

### 不建议的“修复”

- 不建议通过跳过失败测试、篡改测试数据或捕获异常后返回空结果来“通过”测试。
- 不建议仅设置 `FLAGS_enable_pir_api=0`：PaddleX 会通过 `config.enable_new_ir(True)` 显式启用新 IR，单独改该标志不可靠，且本轮未验证。
- 不建议删除或重新下载模型：现有模型完整，问题与模型文件无关。

---

## 12. 修复方案的风险

### 方案 A（关闭 MKLDNN）

| 风险 | 说明 |
| --- | --- |
| CPU 推理性能下降 | oneDNN 是 CPU 加速路径；关闭后单页耗时可能上升。历史报告 CPU 单页约 7.7–10.4 秒，修复后需重新测量。 |
| 数值细微差异 | oneDNN 与 Paddle 原生 CPU kernel 的浮点累加顺序可能不同，理论上可能造成极小的识别结果差异，需用标准答案回归验证。 |
| 影响范围 | 若使用环境变量 A2，会影响同一进程中所有 PaddleX 模型的默认 run_mode；若使用代码 A1，仅影响 PP-StructureV3。 |
| 不解决根因 | 这是规避 PaddlePaddle 3.3.1 oneDNN 缺陷，不是修复 Paddle 本身；未来升级 Paddle 后可重新评估是否恢复 MKLDNN。 |
| 内存 | 可能略有变化，需观察，但通常不是主要风险。 |

### 方案 B（降级 PaddlePaddle）

| 风险 | 说明 |
| --- | --- |
| 依赖锁定变化 | 需要修改 `uv.lock`/环境，可能触发其他包重新解析。 |
| 回归风险 | 3.2.0 与 PaddleX 3.7.2 的实际兼容性未在当前环境验证。 |
| 安装风险 | 需要联网下载约 100 MB 级 wheel；本轮禁止。 |
| 可逆性 | 降级后回滚需要重新安装 3.3.1，需提前备份环境。 |

### 方案 C（升级 PaddlePaddle）

- 未知修复版本，未知回归范围，风险不可评估。

### 方案 D（GPU 版 PaddlePaddle）

- CUDA/cuDNN/驱动/GPU 架构兼容性风险最高；RTX 5060 Laptop 是否被当前 wheel 支持尚未确认。

---

## 13. 是否可能影响 Word 提取

**不会。**

依据：

- Word 提取使用 `python-docx`，代码路径在 `core\word_parser.py`。
- `word_parser.py` 不导入 `paddle`、`paddleocr`、`paddlex`。
- 修复方案 A 只改变 PaddleX 的 CPU oneDNN 默认值，不涉及 Word 解析。
- 方案 A2 的环境变量仅被 PaddleX 读取，Word 解析不会读取。
- 当前 134 项测试中 Word 相关测试未出现在 PDF 失败集中。

需要注意：如果未来把环境变量设置成影响全局 Python 的配置，仍应确认 Word 路径没有间接导入 PaddleX；当前代码没有这种依赖。

---

## 14. 是否可能影响项目二、项目三

**方案 A（推荐）不会影响项目二、项目三。**

理由：

- 不修改项目二、项目三的任何文件。
- 不修改共享依赖版本。
- 不改变项目一导出的 JSON/Excel 字段结构。
- 项目二读取的仍然是相同的 `DocumentResult` / `EnvironmentalRecord` / `TableData` 结构。
- 项目三调用的仍然是项目一的 CLI/API 入口，行为从“PDF 失败”变为“PDF 成功”，属于修复而非破坏。

需要注意：

- 如果项目二/项目三与项目一共享同一个 `.venv`，任何依赖变更（方案 B/C/D）都会影响它们；方案 A 不涉及依赖变更，因此无此风险。
- 如果后续采用方案 B（降级 PaddlePaddle），必须先确认项目二/项目三是否也使用项目一的 `.venv`，并在独立环境验证。
- 本轮未读取或修改项目二、项目三。

---

## 15. 推荐的修复顺序

1. **先备份环境信息**（见第 16 节），确认可回滚。
2. **优先采用方案 A1**：在 `PaddleStructureParser` 创建 `PPStructureV3` 时传入 `enable_mkldnn=False`。
3. 先运行最小 PDF 回归：
   - `tests\pdf_table_special\samples\scanned_special_values.pdf`
   - 确认 `predict_ok`、表格数量、行列数、OCR 行数正常。
4. 运行 PDF 相关测试：
   - `tests\test_pdf_parser.py`
   - `tests\test_pdf_table_parsing.py`
   - `tests\pdf_table_special\`
   - `tests\test_real_test_data.py` 中的 PDF 用例
5. 运行项目一完整测试套件，确认 134 项结果。
6. 如果方案 A1 仍有个别 PDF 失败，再分析是否属于识别精度问题，而不是 Paddle 运行时异常。
7. 只有在方案 A1 无法接受（例如性能明显不达标）时，才在**独立克隆环境**中评估方案 B（PaddlePaddle 3.2.0）。
8. 方案 C/D 仅作为后续版本跟踪，不在本轮或下一轮直接实施。

---

## 16. 修复前的环境备份和回滚建议

### 16.1 备份

项目不是 Git 仓库，无法用 Git commit 作为检查点。修复前建议：

1. 记录完整依赖快照：

```powershell
.\.venv\Scripts\python.exe -m pip freeze > D:\backup\project1_pip_freeze_20261101.txt
```

2. 备份将要修改的文件（方案 A1 只涉及一个文件）：

```powershell
Copy-Item "src\doc_extractor\core\paddle_structure.py" `
  "D:\backup\paddle_structure.py.20261101.bak"
```

3. 备份依赖锁定与配置（只复制，不修改）：

```text
uv.lock
requirements.txt
pyproject.toml
run_project1.bat
```

4. 记录模型缓存位置与完整性：

```text
D:\DocumentAuditSystem\project1_extraction\.paddlex_cache\official_models
```

当前模型文件最后修改时间仍为 2026-10-28，本轮诊断未修改模型。

5. 如需更稳妥，可在修复前对整个 `.venv` 目录做文件级备份，或使用 Windows 系统还原点。`.venv` 体积较大，需确认磁盘空间。

### 16.2 回滚

| 修复方式 | 回滚操作 |
| --- | --- |
| A1 代码增加 `enable_mkldnn=False` | 删除该行，恢复备份文件 |
| A2 环境变量 | 删除/取消 `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` |
| B 降级 PaddlePaddle | 按备份的 `pip freeze` 和 `uv.lock` 恢复原版本 |
| C 升级 PaddlePaddle | 同上，恢复原版本 |
| D 安装 GPU 版 | 卸载 GPU 版，恢复 CPU 版及原依赖 |

### 16.3 修复后必须重新验证

- PDF 单页、表格页、扫描页。
- 真实 `test_data` 中两份 PDF。
- 21 条环境数据标准答案。
- JSON/Excel 导出。
- Word 提取回归。
- 项目二、项目三入口（若它们依赖项目一输出）。

---

## 17. 诊断记录与限制

### 17.1 使用的测试文件

| 文件 | SHA-256 |
| --- | --- |
| `tests\pdf_table_special\samples\scanned_special_values.pdf` | `E95E4C2167F2690F920E2565597A84FF0E14C6AF2F0C3A1BF74409F61FB75622` |
| `tests\pdf_table_special\samples\bordered_special_values.pdf` | `D9C00534547845284B586D4BFB4B3E5B1DC53E48C9A40026B10820A59D8E378D` |
| `tests\pdf_table_special\samples\borderless_native.pdf` | `467D6C92A2E6DA4EF21C8C7B434DD1F7BDE3B9BCA245509E563F2F623FB2D852` |

真实 `test_data` PDF：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `02_企业废气监测报告.pdf` | 3160 | `6FCB197671CCCAF37BCB8FC54963BC97F337C0915B4F084CD3DCE5DC610051B6` |
| `04_企业年度环境统计报告.pdf` | 3128 | `02985E91562F74B2C6882AB3F954F6A06B9BF6752FA5F87F7F99C22408B56F48` |

### 17.2 诊断执行情况

- 所有诊断脚本只写入系统临时目录：`C:\Users\孙强强\AppData\Local\Temp\opencode`。
- 未安装、卸载、升级、降级任何依赖。
- 未删除或重新下载模型。
- 未修改原始 Word/PDF 测试数据。
- 未修改项目源码、配置、`requirements.txt`、`pyproject.toml`、`uv.lock`。
- 未调用云端 API。
- 未读取或输出 API Token。
- 诊断推理使用项目一现有 `.paddlex_cache`；执行后模型文件时间戳未变化，`func_ret` 与 `locks` 为空。

### 17.3 尚未确认项

1. 触发 `ArrayAttribute<DoubleAttribute>` 的精确 Paddle op 和属性名。
2. PaddlePaddle 3.3.1 的哪个补丁版本修复了该 oneDNN/PIR 转换问题。
3. PaddlePaddle 3.2.0 在当前 venv 中的实际回归结果（历史文档记录为通过，但本轮未复验）。
4. 关闭 oneDNN 后的真实性能损耗和识别精度变化（本轮只验证了推理成功，未做完整基准）。
5. GPU 版 PaddlePaddle 对 RTX 5060 Laptop 的支持情况。
6. `opencv-python 5.0.0.93` 残留元数据是否会在未来重装/升级时造成文件覆盖问题（当前运行时为 4.10.0，未观察到故障）。

---

## 18. 最终建议

**建议采用方案 A1：在 `PaddleStructureParser` 创建 `PPStructureV3` 时显式传入 `enable_mkldnn=False`。**

它满足：

- 不安装/卸载/降级任何依赖。
- 不修改模型。
- 改动最小（1 行）。
- 已用真实测试 PDF 验证可绕过当前 PaddlePaddle 3.3.1 的 oneDNN/PIR 缺陷。
- 不影响 Word 提取。
- 不改变项目二、项目三的数据契约。

在用户确认前，不应执行修复；本轮诊断到此停止。
