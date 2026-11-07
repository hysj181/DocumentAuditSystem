# 项目三：文档智能审核 Web 应用

基于 FastAPI、Jinja2 和 Uvicorn 的本地 Web 应用。网页上传 Word/PDF 后，通过 Python 模块 API 调用项目一提取内容和项目二执行审核、定位、Word 原生批注或 PDF 红色矩形标注。

## 启动

在项目三目录执行：

```powershell
uv run uvicorn project3_web.app:app --host 127.0.0.1 --port 8000
```

访问：

```text
http://127.0.0.1:8000/
```

## 页面

- `/`：系统介绍和最近任务。
- `/upload`：多文件上传，支持 `.docx` 和 `.pdf`。
- `/tasks`：历史任务列表。
- `/tasks/{task_id}/status`：处理状态，处理中自动刷新。
- `/tasks/{task_id}`：审核结果、问题、批注、报告和下载。
- `/tasks/{task_id}/download/{artifact_id}`：安全下载标注文件或报告。

## 调用关系

```text
Web 上传
  -> doc_extractor.api.extract_files()
  -> doc_extractor.api.save_batch()
  -> word_audit.pipeline.run_audit()
  -> 项目二标注副本 / JSON / Markdown 报告
```

项目三不通过 subprocess 调用其他项目，也不修改项目一/项目二源码。

## 任务存储

默认任务目录：

```text
project3_web/data/tasks/<task_id>/
├── task.json
├── uploads/
├── extraction/
└── audit/
    ├── annotated/
    └── reports/
```

每个任务有独立目录，任务之间不覆盖。可通过环境变量修改：

```powershell
$env:DOCUMENT_AUDIT_DATA_DIR = "D:\path\to\data"
```

单个上传文件默认上限为 50 MB，可通过
`DOCUMENT_AUDIT_MAX_UPLOAD_BYTES` 调整。

## Word 与 PDF

- Word：项目二使用 OOXML 原生批注，精确定位正文或表格文字，不向正文插入红字。
- PDF：保持项目二红色矩形描边，依赖 PDF 文本层和 bbox。
- 原始上传文件只读；标注文件、报告均写入任务输出目录。
- 没有审核问题或没有成功批注时，不生成标注副本，并显示原因。

## 测试

```powershell
uv run pytest tests -q
uv run ruff check src tests
```

Web 测试覆盖 Word/PDF 上传、真实提取、真实审核、原生批注下载、PDF 标注下载、报告下载、错误任务、任务隔离和路径安全。
