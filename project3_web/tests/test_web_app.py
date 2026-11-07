from __future__ import annotations

import hashlib
import io
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pymupdf
from docx import Document
from fastapi.testclient import TestClient
from project3_web.app import create_app

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PROCESSING = {"queued", "extracting", "auditing"}


def _word_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 100), text, fontsize=18, fontname="china-s")
    data = document.tobytes()
    document.close()
    return data


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _upload(client: TestClient, files: list[tuple[str, bytes]]):
    return client.post(
        "/upload",
        files=[
            (
                "files",
                (
                    name,
                    content,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if name.endswith(".docx")
                    else "application/pdf",
                ),
            )
            for name, content in files
        ],
        follow_redirects=False,
    )


def _task_id(response) -> str:
    assert response.status_code == 303
    location = response.headers["location"]
    return location.rstrip("/").split("/")[-2]


def _wait_for_task(client: TestClient, app, task_id: str) -> dict:
    for _ in range(120):
        task = app.state.task_store.load(task_id)
        if task is not None and task.get("status") not in PROCESSING:
            return task
        client.get(f"/tasks/{task_id}")
        time.sleep(0.05)
    raise AssertionError(f"task did not finish: {task_id}")


def _comment_text(comment: ElementTree.Element) -> str:
    return "\n".join(
        "".join(element.text or "" for element in paragraph.iter(f"{W}t"))
        for paragraph in comment.findall(f"{W}p")
    )


def _comment_range_text(document_xml: bytes, comment_id: int) -> str:
    root = ElementTree.fromstring(document_xml)
    identifier = str(comment_id)
    inside = False
    parts: list[str] = []
    for element in root.iter():
        if (
            element.tag == f"{W}commentRangeStart"
            and element.get(f"{W}id") == identifier
        ):
            inside = True
            continue
        if (
            element.tag == f"{W}commentRangeEnd"
            and element.get(f"{W}id") == identifier
        ):
            inside = False
            continue
        if inside and element.tag == f"{W}t":
            parts.append(element.text or "")
    return "".join(parts)


def _assert_native_word_comment(
    data: bytes,
    *,
    anchor_text: str = "数剧",
    suggestion: str = "数据",
) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "word/comments.xml" in names
        comments = ElementTree.fromstring(
            archive.read("word/comments.xml")
        ).findall(f"{W}comment")
        assert len(comments) == 1
        comment = comments[0]
        comment_id = int(comment.get(f"{W}id"))
        text = _comment_text(comment)
        assert "数剧" in text
        assert suggestion in text
        document_xml = archive.read("word/document.xml")
    assert _comment_range_text(document_xml, comment_id) == anchor_text


def test_home_and_upload_pages(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)

    home = client.get("/")
    assert home.status_code == 200
    assert "文档智能审核系统" in home.text
    assert "上传文档" in home.text

    upload = client.get("/upload")
    assert upload.status_code == 200
    assert "选择或拖入多个文档" in upload.text
    assert "上传并开始审核" in upload.text

    tasks = client.get("/tasks")
    assert tasks.status_code == 200


def test_upload_rejects_unsupported_file_type(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    response = _upload(client, [("notes.txt", b"not allowed")])
    assert response.status_code == 400
    assert "不支持的文件类型" in response.text


def test_upload_rejects_empty_file(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    response = _upload(client, [("empty.docx", b"")])
    assert response.status_code == 400
    assert "空文件" in response.text


def test_word_upload_real_end_to_end(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    word = _word_bytes(
        "本次企业数剧审核验收",
        "本段为正常文字，不应被修改。",
    )
    source_hash = _sha256(word)

    response = _upload(client, [("acceptance.docx", word)])
    task_id = _task_id(response)
    task = _wait_for_task(client, app, task_id)
    assert task["status"] == "completed", task
    assert task["error"] is None
    assert len(task["uploads"]) == 1
    assert task["uploads"][0]["sha256"] == source_hash
    assert len(task["extraction"]["documents"]) == 1
    assert task["extraction"]["documents"][0]["record_count"] == 2

    counts = task["audit"]["counts"]
    assert counts["issue_count"] == 1
    assert counts["located_count"] == 1
    assert counts["annotation_applied_count"] == 1
    assert counts["annotation_failed_count"] == 0
    assert counts["annotation_manual_review_count"] == 0
    assert task["audit"]["complete_success"] is True
    assert task["audit"]["typo_counts"]["typo_issue_count"] == 1

    status_page = client.get(f"/tasks/{task_id}/status")
    assert status_page.status_code == 200
    assert "已完成" in status_page.text
    assert f"/tasks/{task_id}" in status_page.text

    tasks_page = client.get("/tasks")
    assert tasks_page.status_code == 200
    assert task_id in tasks_page.text

    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    assert "批注成功" in detail.text
    assert "数剧" in detail.text

    artifacts = task["artifacts"]
    assert "word_1" in artifacts
    assert "audit_json" in artifacts
    assert "audit_markdown" in artifacts
    assert "annotation_json" in artifacts
    assert "annotation_markdown" in artifacts

    word_download = client.get(f"/tasks/{task_id}/download/word_1")
    assert word_download.status_code == 200
    assert word_download.content[:2] == b"PK"
    _assert_native_word_comment(word_download.content)

    reopened = Document(io.BytesIO(word_download.content))
    assert [paragraph.text for paragraph in reopened.paragraphs] == [
        "本次企业数剧审核验收",
        "本段为正常文字，不应被修改。",
    ]

    json_download = client.get(f"/tasks/{task_id}/download/audit_json")
    assert json_download.status_code == 200
    assert "manual_acceptance" not in json_download.text
    assert '"issue_count": 1' in json_download.text

    markdown_download = client.get(f"/tasks/{task_id}/download/audit_markdown")
    assert markdown_download.status_code == 200
    assert "完整审核报告" in markdown_download.text

    upload_path = (
        app.state.task_store.root
        / task_id
        / "uploads"
        / task["uploads"][0]["stored_name"]
    )
    assert _sha256(upload_path.read_bytes()) == source_hash


def test_pdf_upload_real_annotation_download(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    pdf = _pdf_bytes("本次企业数剧审核验收")
    source_hash = _sha256(pdf)

    response = _upload(client, [("acceptance.pdf", pdf)])
    task_id = _task_id(response)
    task = _wait_for_task(client, app, task_id)
    assert task["status"] == "completed", task
    assert task["uploads"][0]["sha256"] == source_hash
    counts = task["audit"]["counts"]
    assert counts["issue_count"] == 1
    assert counts["annotation_applied_count"] == 1
    assert counts["annotation_failed_count"] == 0
    assert counts["annotation_manual_review_count"] == 0
    assert "pdf_1" in task["artifacts"]

    download = client.get(f"/tasks/{task_id}/download/pdf_1")
    assert download.status_code == 200
    assert download.content[:4] == b"%PDF"
    with pymupdf.open(stream=download.content, filetype="pdf") as annotated:
        page = annotated.load_page(0)
        assert "数剧" in page.get_text("text")
        red_drawings = [
            drawing
            for drawing in page.get_drawings()
            if drawing.get("color")
            and drawing["color"][0] > 0.99
            and drawing["color"][1] < 0.01
            and drawing["color"][2] < 0.01
        ]
        assert len(red_drawings) == 1

    upload_path = (
        app.state.task_store.root
        / task_id
        / "uploads"
        / task["uploads"][0]["stored_name"]
    )
    assert _sha256(upload_path.read_bytes()) == source_hash


def test_multiple_word_files_share_one_task(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    first = _word_bytes("本次企业数剧审核验收")
    second = _word_bytes("本段为正常文字，不应被修改。")

    response = _upload(
        client,
        [
            ("first.docx", first),
            ("second.docx", second),
        ],
    )
    task_id = _task_id(response)
    task = _wait_for_task(client, app, task_id)
    assert task["status"] == "completed"
    assert len(task["uploads"]) == 2
    assert len(task["extraction"]["documents"]) == 2
    assert task["audit"]["counts"]["annotation_applied_count"] == 1
    assert "word_1" in task["artifacts"]


def test_no_issue_task_has_reports_but_no_annotated_file(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    word = _word_bytes("本段为正常文字，不应被修改。")
    response = _upload(client, [("normal.docx", word)])
    task_id = _task_id(response)
    task = _wait_for_task(client, app, task_id)

    assert task["status"] == "completed"
    assert task["audit"]["counts"]["issue_count"] == 0
    assert task["audit"]["counts"]["annotation_applied_count"] == 0
    assert "word_1" not in task["artifacts"]
    assert "audit_json" in task["artifacts"]
    assert "audit_markdown" in task["artifacts"]

    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    assert "未发现审核问题" in detail.text


def test_corrupt_word_fails_clearly(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    response = _upload(client, [("broken.docx", b"not a valid docx")])
    task_id = _task_id(response)
    task = _wait_for_task(client, app, task_id)

    assert task["status"] == "failed"
    assert task["error"] == "所有文档提取失败"
    assert task["extraction"]["documents"][0]["error"]
    assert task["audit"] is None

    detail = client.get(f"/tasks/{task_id}")
    assert detail.status_code == 200
    assert "所有文档提取失败" in detail.text


def test_task_isolation_and_download_safety(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data")
    client = TestClient(app)
    word = _word_bytes("本次企业数剧审核验收")

    first_response = _upload(client, [("first.docx", word)])
    first_id = _task_id(first_response)
    _wait_for_task(client, app, first_id)
    normal = _word_bytes("本段为正常文字，不应被修改。")
    second_response = _upload(client, [("second.docx", normal)])
    second_id = _task_id(second_response)
    _wait_for_task(client, app, second_id)

    assert first_id != second_id
    first_download = client.get(f"/tasks/{first_id}/download/word_1")
    assert first_download.status_code == 200

    second_download = client.get(f"/tasks/{second_id}/download/word_1")
    assert second_download.status_code == 404

    missing = client.get(f"/tasks/{first_id}/download/not_an_artifact")
    assert missing.status_code == 404

    traversal = client.get(f"/tasks/{first_id}/download/..%2F..%2Ftask.json")
    assert traversal.status_code == 404

    invalid_task = client.get("/tasks/..%2F..%2Fetc/download/word_1")
    assert invalid_task.status_code == 404
