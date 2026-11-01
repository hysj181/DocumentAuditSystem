"""项目三统一错误类型与退出码定义。"""

from __future__ import annotations

from enum import IntEnum
from typing import Final


class ExitCode(IntEnum):
    """项目三 CLI 统一退出码。"""

    SUCCESS = 0
    USER_INPUT = 2
    PARTIAL = 3
    EXTERNAL_FAILURE = 4
    INTERNAL = 5


class Project3Error(Exception):
    """项目三所有可预期错误的基类。"""

    exit_code: Final[ExitCode] = ExitCode.INTERNAL

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UserInputError(Project3Error):
    """用户输入或参数错误。"""

    exit_code = ExitCode.USER_INPUT


class ConfigError(UserInputError):
    """项目路径或 Python 解释器配置无效。"""


class InputError(UserInputError):
    """输入路径、文件类型或文件读取错误。"""


class PartialCompletionError(Project3Error):
    """流程已执行，但存在未完成或需人工核实的部分。"""

    exit_code = ExitCode.PARTIAL


class ExternalStageError(Project3Error):
    """项目一或项目二阶段执行失败。"""

    exit_code = ExitCode.EXTERNAL_FAILURE


class Project1StageError(ExternalStageError):
    """项目一提取或批次校验失败。"""


class BatchValidationError(Project1StageError):
    """项目一 batch.json 不存在、格式错误或结构无效。"""


class Project2StageError(ExternalStageError):
    """项目二审核或审核报告校验失败。"""


class AuditValidationError(Project2StageError):
    """项目二审核报告不存在、格式错误或结构无效。"""


class InternalError(Project3Error):
    """项目三内部错误。"""

    exit_code = ExitCode.INTERNAL


class ManifestError(InternalError):
    """任务目录或 manifest 写入错误。"""


class TaskLockError(InternalError):
    """任务已被其他进程锁定。"""


def classify_exception(exc: BaseException) -> ExitCode:
    """将异常归类为项目三退出码。"""

    if isinstance(exc, Project3Error):
        return exc.exit_code
    return ExitCode.INTERNAL
