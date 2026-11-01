"""错误类型、错误分类和退出码测试。"""

from __future__ import annotations

import pytest

from project3_cli_workflow.errors import (
    AuditValidationError,
    BatchValidationError,
    ConfigError,
    ExitCode,
    ExternalStageError,
    InputError,
    InternalError,
    ManifestError,
    PartialCompletionError,
    Project1StageError,
    Project2StageError,
    Project3Error,
    UserInputError,
    classify_exception,
)


def test_exit_code_values() -> None:
    """退出码必须与阶段 1 约定一致。"""

    assert int(ExitCode.SUCCESS) == 0
    assert int(ExitCode.USER_INPUT) == 2
    assert int(ExitCode.PARTIAL) == 3
    assert int(ExitCode.EXTERNAL_FAILURE) == 4
    assert int(ExitCode.INTERNAL) == 5


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (UserInputError("输入错误"), ExitCode.USER_INPUT),
        (ConfigError("配置错误"), ExitCode.USER_INPUT),
        (InputError("文件输入错误"), ExitCode.USER_INPUT),
        (PartialCompletionError("部分完成"), ExitCode.PARTIAL),
        (ExternalStageError("外部阶段失败"), ExitCode.EXTERNAL_FAILURE),
        (Project1StageError("项目一失败"), ExitCode.EXTERNAL_FAILURE),
        (BatchValidationError("批次无效"), ExitCode.EXTERNAL_FAILURE),
        (Project2StageError("项目二失败"), ExitCode.EXTERNAL_FAILURE),
        (AuditValidationError("报告无效"), ExitCode.EXTERNAL_FAILURE),
        (InternalError("内部错误"), ExitCode.INTERNAL),
        (ManifestError("清单写入错误"), ExitCode.INTERNAL),
        (Project3Error("未分类项目错误"), ExitCode.INTERNAL),
        (ValueError("普通异常"), ExitCode.INTERNAL),
    ],
)
def test_classify_exception(
    error: BaseException,
    expected: ExitCode,
) -> None:
    """项目异常映射到约定退出码，未知异常归为内部错误。"""

    assert classify_exception(error) is expected


def test_error_message_is_preserved() -> None:
    """错误对象保留原始消息，便于 CLI 输出。"""

    error = ConfigError("项目一根目录不存在")
    assert error.message == "项目一根目录不存在"
    assert str(error) == "项目一根目录不存在"
