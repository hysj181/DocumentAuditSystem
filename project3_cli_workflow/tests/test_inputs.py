"""输入路径解析、文件夹展开和文件过滤测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from project3_cli_workflow.errors import InputError
from project3_cli_workflow.inputs import collect_inputs
from project3_cli_workflow.models import (
    FILTER_REASON_DUPLICATE,
    FILTER_REASON_UNSUPPORTED,
)


def _write(path: Path, content: str = "测试内容") -> Path:
    """创建测试文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_single_docx_uppercase_extension(tmp_path: Path) -> None:
    """单个 DOCX 文件应被接受，扩展名大小写不敏感。"""

    source = _write(tmp_path / "报告.DOCX")

    result = collect_inputs([source])

    assert result.files == [source.resolve()]
    assert result.filtered == []


def test_single_pdf(tmp_path: Path) -> None:
    """单个 PDF 文件应被接受。"""

    source = _write(tmp_path / "报告.PDF")

    result = collect_inputs([source])

    assert result.files == [source.resolve()]


def test_multiple_files_keep_user_order(tmp_path: Path) -> None:
    """多个显式文件按用户输入顺序保留。"""

    second = _write(tmp_path / "b.pdf")
    first = _write(tmp_path / "a.docx")

    result = collect_inputs([second, first])

    assert result.files == [second.resolve(), first.resolve()]


def test_folder_non_recursive(tmp_path: Path) -> None:
    """非递归扫描只处理当前文件夹。"""

    _write(tmp_path / "b.pdf")
    _write(tmp_path / "a.docx")
    _write(tmp_path / "sub" / "c.docx")
    _write(tmp_path / "note.txt")

    result = collect_inputs([tmp_path])

    assert [path.name for path in result.files] == ["a.docx", "b.pdf"]
    assert any(
        item.reason == FILTER_REASON_UNSUPPORTED and item.file_name == "note.txt"
        for item in result.filtered
    )


def test_folder_recursive(tmp_path: Path) -> None:
    """递归扫描包含子文件夹中的文件。"""

    _write(tmp_path / "a.docx")
    _write(tmp_path / "sub" / "b.pdf")
    _write(tmp_path / "sub" / "deep" / "c.DOCX")

    result = collect_inputs([tmp_path], recursive=True)

    assert [path.name for path in result.files] == ["a.docx", "b.pdf", "c.DOCX"]


def test_folder_scan_is_stable(tmp_path: Path) -> None:
    """相同文件夹的扫描结果顺序稳定。"""

    _write(tmp_path / "z.docx")
    _write(tmp_path / "a.docx")
    _write(tmp_path / "m.pdf")

    first = collect_inputs([tmp_path])
    second = collect_inputs([tmp_path])

    assert [path.name for path in first.files] == ["a.docx", "m.pdf", "z.docx"]
    assert first.files == second.files


def test_unsupported_extension_is_recorded(tmp_path: Path) -> None:
    """不支持的文件应进入过滤清单，而不是静默忽略。"""

    docx = _write(tmp_path / "报告.docx")
    unsupported = _write(tmp_path / "说明.txt")

    result = collect_inputs([docx, unsupported])

    assert result.files == [docx.resolve()]
    assert len(result.filtered) == 1
    assert result.filtered[0].source_path == str(unsupported.resolve())
    assert result.filtered[0].reason == FILTER_REASON_UNSUPPORTED


def test_nonexistent_path_raises(tmp_path: Path) -> None:
    """输入路径不存在时给出明确错误。"""

    with pytest.raises(InputError, match="输入路径不存在"):
        collect_inputs([tmp_path / "missing.docx"])


def test_empty_folder_raises(tmp_path: Path) -> None:
    """空文件夹没有可处理文件时给出明确提示。"""

    with pytest.raises(InputError, match="未找到可处理"):
        collect_inputs([tmp_path])


def test_duplicate_input_is_filtered(tmp_path: Path) -> None:
    """重复输入同一文件只保留一次。"""

    source = _write(tmp_path / "报告.docx")

    result = collect_inputs([source, source, tmp_path / "." / source.name])

    assert result.files == [source.resolve()]
    assert len(result.filtered) == 2
    assert all(
        item.reason == FILTER_REASON_DUPLICATE for item in result.filtered
    )


def test_chinese_path_and_file_name(tmp_path: Path) -> None:
    """中文目录和中文文件名应正常解析。"""

    source = _write(tmp_path / "企业资料" / "废水监测报告.DOCX")

    result = collect_inputs([tmp_path / "企业资料"])

    assert result.files == [source.resolve()]
    assert result.files[0].name == "废水监测报告.DOCX"


def test_explicit_unsupported_only_raises(tmp_path: Path) -> None:
    """只有不支持文件时没有有效输入，应返回明确错误。"""

    unsupported = _write(tmp_path / "说明.txt")

    with pytest.raises(InputError, match="未找到可处理"):
        collect_inputs([unsupported])
