# 企业环境数据智能审核系统

本仓库由文档提取、审核标注、CLI 编排和 Web 应用四部分组成：

| 目录 | 职责 |
| --- | --- |
| `project1_extraction` | Word/PDF 内容提取，生成标准化 `batch.json` 和环境数据记录 |
| `project2_word_audit` | 数学表达式校验、保守错别字检查、问题定位、Word 原生批注和 PDF 红色矩形标注 |
| `project3_cli_workflow` | 通过 CLI 编排项目一和项目二，管理任务、复用、恢复、日志和最终交付 |
| `project3_web` | FastAPI + Jinja2 + Uvicorn 本地 Web 应用，网页上传文档、查看审核结果并下载标注文件 |

系统坚持“原始文件只读、输出独立”的原则：不修改原始 Word/PDF，不覆盖历史任务，不自动替用户确认审核结论。

## 1. 技术路线

- Python 3.12
- uv 管理各项目虚拟环境
- 项目一：`python-docx`、PyMuPDF、PaddleOCR/PaddleX
- 项目二：`python-docx`、PyMuPDF、OOXML 原生批注
- 项目三 Web：FastAPI、Uvicorn、Jinja2、HTML/CSS/JavaScript
- 项目三 CLI：保留现有子进程编排方式

Web 集成通过 Python 模块 API 调用项目一和项目二，不通过 `subprocess` 调用其他项目命令行：

```text
doc_extractor.api.extract_files()
doc_extractor.api.save_batch()
word_audit.pipeline.run_audit()
```

## 2. 主要能力

- 支持 `.docx` 和 `.pdf` 多文件上传，拒绝不支持的类型和空文件。
- 检查上传文件大小，默认单文件上限 50 MB。
- 每次审核创建独立任务目录，任务之间不覆盖。
- 调用项目一真实提取 API，保存批次 JSON。
- 调用项目二真实 `run_audit()`，保留现有数学、错别字、定位和标注规则。
- Word 使用 OOXML 原生批注，精确定位正文或表格中的目标文字。
- 数学问题只使用 `reported_value` 对应数字 token 作为锚点；不使用 raw_expression、computed_value 或整格文本。
- 低置信度错别字不自动批注，进入人工复核。
- PDF 保持红色矩形描边标注。
- 网页展示提取记录数、审核问题数、错别字数、定位数、批注成功/失败数和人工复核数。
- 网页下载标注后的 Word/PDF、审核 JSON/Markdown 和批注明细报告。
- 下载路径经过任务目录校验，防止路径穿越。
- 未发现问题或没有成功批注时，不生成标注副本，并在页面说明原因。
- 未验证不等于审核正确：`unverified` 只表示没有可验证的明确计算表达式。

## 3. 目录结构

```text
<仓库根目录>/
├── README.md
├── .gitignore
├── docs/                              # 版本、验收、已知问题等总文档
├── project1_extraction/               # Word/PDF 提取
│   ├── src/doc_extractor/
│   ├── tests/
│   ├── test_data/                     # 原始测试数据，只读
│   ├── docs/
│   ├── main.py
│   └── README.md
├── project2_word_audit/               # 数学审核、错别字、定位、Word/PDF 标注
│   ├── src/word_audit/
│   ├── tests/
│   ├── test_data/
│   ├── docs/
│   ├── main.py
│   └── README.md
├── project3_cli_workflow/             # 统一 CLI 编排和交付
│   ├── src/project3_cli_workflow/
│   ├── tests/
│   ├── docs/
│   └── README.md
└── project3_web/                      # 本地 Web 应用
    ├── src/project3_web/
    │   ├── app.py
    │   ├── services.py
    │   ├── task_store.py
    │   ├── templates/
    │   └── static/
    ├── tests/
    ├── data/                          # 本地任务数据，默认忽略
    ├── pyproject.toml
    └── README.md
```

## 4. 安装

每个项目在各自目录使用 uv 安装依赖：

```powershell
cd <仓库根目录>/project1_extraction
uv sync

cd <仓库根目录>/project2_word_audit
uv sync

cd <仓库根目录>/project3_cli_workflow
uv sync

cd <仓库根目录>/project3_web
uv sync
```

项目一和项目二保留各自独立 `.venv`。项目三 Web 的 `pyproject.toml` 使用本地可编辑依赖引用项目一和项目二。

## 5. 启动 Web 应用

```powershell
cd <仓库根目录>/project3_web
uv run uvicorn project3_web.app:app --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000/
```

页面：

- `/`：系统介绍和最近任务
- `/upload`：多文件上传
- `/tasks`：任务列表
- `/tasks/{task_id}/status`：处理状态，处理中自动刷新
- `/tasks/{task_id}`：审核结果详情
- `/tasks/{task_id}/download/{artifact_id}`：安全下载标注文件或报告
- `/health`：健康检查

可通过环境变量修改本地任务目录：

```powershell
$env:DOCUMENT_AUDIT_DATA_DIR = "D:\path\to\data"
```

默认任务目录为 `project3_web/data/tasks/<task_id>/`，包含：

```text
task.json
uploads/
extraction/
audit/annotated/
audit/reports/
```

该目录已通过 `.gitignore` 排除，不会上传 GitHub。

## 6. 运行 CLI 工作流

项目三 CLI 仍保留原有编排方式。示例：

```powershell
cd <仓库根目录>/project3_cli_workflow
uv run project3 run `
  "../project1_extraction/test_data/01_企业废水监测报告.docx" `
  "../project1_extraction/test_data/02_企业废气监测报告.pdf" `
  --output-root "<输出根目录>"
```

文件夹输入：

```powershell
uv run project3 run "<待审核目录>" --output-root "<输出根目录>"
uv run project3 run "<待审核目录>" --recursive --output-root "<输出根目录>"
```

断点恢复和重新交付：

```powershell
uv run project3 resume <job_id> --output-root "<输出根目录>"
uv run project3 deliver --manifest "<输出根目录>/<job_id>/manifest.json"
```

项目一和项目二的独立 CLI 用法见各自 README。

## 7. 审核语义

| 状态 | 含义 |
| --- | --- |
| `verified` | 明确表达式已计算且与报告值一致 |
| `unverified` | 没有明确计算表达式，无法验证，不表示审核通过 |
| `error` | 明确表达式计算结果与报告值不一致，生成审核问题 |
| `located` | 索引/坐标和原文文本核对通过 |
| `ambiguous` / `not_found` / `invalid_location` | 不能安全定位，进入人工复核 |
| `applied` | 已写入批注或标记 |
| `failed` | 写入失败 |
| `skipped` | 因定位未通过、低置信度或锚点冲突进入人工复核 |

`complete_success=true` 只表示项目二流程完整，不代表数据合规或所有业务规则已验证。

## 8. Word 与 PDF 标注

### Word

- 使用 OOXML 原生批注。
- 不向正文插入红色提示段落。
- 数学问题只锚定 `reported_value` 对应数字 token。
- 错别字问题只锚定错误词。
- 重复、重叠或无法精确唯一的锚点安全跳过并进入人工复核。
- 保留已有批注；事务失败只回滚本次操作。
- 原始 DOCX 只读，标注文件写入独立副本。
- Word 原生批注已通过独立 OOXML 测试和人工打开验证。

### PDF

- 在页面 bbox 对应区域绘制红色矩形描边，不填充、不遮挡原文。
- 保留原 PDF 文本层。
- 页面旋转、无文本层扫描件、无效 bbox 进入人工复核。
- 原始 PDF 只读，标注文件写入独立副本。

## 9. 安全和数据保护

- 原始 Word/PDF、测试数据和项目一/二核心代码只读。
- 上传文件只写入新任务目录，不覆盖历史上传。
- 下载接口只允许访问任务元数据中登记的 artifact，并校验路径必须位于任务目录内。
- 不提交 `.venv`、本地任务数据、真实企业文档、本地验收文件、缓存、临时输出、密钥或个人配置。
- 云端 OCR Token 只从环境变量读取，不写入代码、日志或 Git。
- Web 应用当前定位为本地单用户工具，未实现登录、多租户和分布式锁。

## 10. 测试

各项目使用统一 uv 环境运行测试。最近一次本机验证结果：

| 项目 | 结果 |
| --- | --- |
| `project2_word_audit` | 240 passed, 66 subtests passed |
| `project3_web` | 11 passed |
| `project1_extraction` / `project3_cli_workflow` | 历史验收结果见各自文档 |

Web 测试覆盖：

- 首页、上传页、任务列表和详情页。
- Word 上传、项目一提取、项目二审核、原生批注下载。
- PDF 上传、真实 OCR、PDF 标注下载。
- 不支持文件类型、空文件、损坏文档。
- 多文件任务、任务隔离、下载路径安全。
- JSON / Markdown 报告下载。
- 源文件 SHA256 前后校验。

运行：

```powershell
cd <仓库根目录>/project3_web
uv run pytest tests -q
uv run ruff check src tests
```

## 11. 已知限制

1. Web 应用为本地单用户工具，没有认证、权限、多租户和 CSRF 防护。
2. PDF 使用 CPU 推理，速度明显慢于 Word。
3. `local_gpu` 是模式标签，当前环境实际使用 CPU。
4. 项目二审核以规则和人工词典为主，不是完整 AI 审核系统。
5. 未验证真实 GPU 推理和云端 OCR API 真实调用。
6. 项目三 CLI 使用单机文件锁，不是分布式锁。
7. 未实现浏览器自动化 UI 测试；Web 页面通过 FastAPI TestClient 和实际 HTTP 请求验证。

## 12. 文档

- `project1_extraction/README.md`
- `project2_word_audit/README.md`
- `project2_word_audit/docs/pipeline.md`
- `project2_word_audit/docs/data_model_design.md`
- `project3_cli_workflow/README.md`
- `project3_web/README.md`
- `docs/测试与验收总报告.md`
- `docs/已知问题与限制.md`
- `docs/版本与环境清单.md`
