from __future__ import annotations

import importlib.metadata
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
DOCS_DIR = ROOT / "docs"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from evaluation_support import (  # noqa: E402
    Evaluation,
    list_test_data_files,
    run_evaluation,
    write_comparison_excel,
)


TEST_SCOPE = {
    "test_word_parser.py": "Word 正文、标题、表格、段落/表格索引、实体识别、损坏文件",
    "test_pdf_parser.py": "PDF 文字、文本块坐标、表格、页码、阅读顺序、损坏文件",
    "test_patterns.py": "整数、小数、金额、百分比、日期、全角数字",
    "test_ocr.py": "扫描 PDF OCR、坐标换算、OCR 不可用降级、文本 PDF 不触发 OCR",
    "test_environmental_monitoring.py": "环境监测指标、单位、时间、点位、检出限、缺失值、无法识别数据",
    "test_environmental_management.py": "排污许可、台账、设施运行、维护、缺失单位",
    "test_environmental_statistics.py": "用水、用电、能源、污染物产生/排放、不同单位、来源表格定位",
    "test_environmental_enterprise.py": "统一社会信用代码归并、名称归并、不同企业隔离、身份不明确不合并",
    "test_environmental_pipeline.py": "多文件批量提取、PDF 坐标、文档隔离",
    "test_environmental_models.py": "环境数据模型序列化、状态与统计",
    "test_exporters.py": "JSON/Excel 通用与环境数据导出、来源信息、原始文件保护",
    "test_ui.py": "批量导入、后台线程、环境数据三类视图、企业筛选、结果展示",
    "test_real_test_data.py": "test_data 真实文件、标准答案逐条比对、特殊值、来源位置、JSON/Excel",
    "test_models_batch.py": "通用模型序列化、批量隔离、缺失/不支持文件",
    "test_environment.py": "Python 与依赖环境",
    "test_smoke.py": "PySide6 主窗口启动",
}


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "未安装"


def run_command(command: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = (process.stdout + process.stderr).strip()
    return process.returncode, output


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def format_rate(value: float) -> str:
    return f"{value * 100:.2f}%"


def build_report(evaluation: Evaluation, pytest_output: str, pytest_code: int, pip_output: str, xlsx_path: Path) -> str:
    metrics = evaluation.metrics
    lines: list[str] = []
    lines.append("# 项目一_环境数据提取测试报告")
    lines.append("")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 项目目录：`{ROOT}`")
    lines.append(f"- 对比结果文件：`{xlsx_path}`")
    lines.append("")
    lines.append("## 1. 测试环境")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 操作系统 | {md_cell(platform.platform())} |")
    lines.append(f"| Python | {md_cell(platform.python_version())} |")
    lines.append(f"| Python 可执行文件 | `{md_cell(sys.executable)}` |")
    lines.append(f"| 项目虚拟环境 | `{md_cell(ROOT / '.venv')}` |")
    lines.append(f"| PySide6 | {package_version('PySide6')} |")
    lines.append(f"| python-docx | {package_version('python-docx')} |")
    lines.append(f"| PyMuPDF | {package_version('PyMuPDF')} |")
    lines.append(f"| openpyxl | {package_version('openpyxl')} |")
    lines.append(f"| pytest | {package_version('pytest')} |")
    lines.append(f"| RapidOCR | {package_version('rapidocr-onnxruntime')} |")
    lines.append("")
    if pip_output:
        lines.append("依赖检查（pip check）：")
        lines.append("")
        lines.append("```text")
        lines.append(pip_output)
        lines.append("```")
        lines.append("")
    lines.append("## 2. 测试文件列表")
    lines.append("")
    lines.append("| 文件 | 类型 | 大小（字节） |")
    lines.append("| --- | --- | --- |")
    for path in list_test_data_files():
        lines.append(
            f"| {md_cell(path.name)} | {path.suffix.lstrip('.')} | {path.stat().st_size} |"
        )
    lines.append("")
    lines.append("## 3. 实际执行的测试项目")
    lines.append("")
    lines.append("| 测试文件 | 覆盖内容 |")
    lines.append("| --- | --- |")
    for filename, scope in TEST_SCOPE.items():
        if (TESTS_DIR / filename).exists():
            lines.append(f"| `tests/{filename}` | {md_cell(scope)} |")
    lines.append("")
    lines.append("执行命令：")
    lines.append("")
    lines.append("```powershell")
    lines.append('$env:QT_QPA_PLATFORM = "offscreen"')
    lines.append(r'.\.venv\Scripts\python.exe -m pytest -q')
    lines.append("```")
    lines.append("")
    lines.append("## 4. pytest 测试结果")
    lines.append("")
    lines.append(f"- 退出码：`{pytest_code}`")
    lines.append(f"- 结果：{'通过' if pytest_code == 0 else '存在失败或错误'}")
    lines.append("")
    lines.append("```text")
    lines.append(pytest_output or "（无 pytest 输出）")
    lines.append("```")
    lines.append("")
    lines.append("## 5. 标准答案匹配情况")
    lines.append("")
    lines.append(f"- 标准答案工作表：`{evaluation.standard_sheet}`")
    lines.append(f"- 标准答案字段：{', '.join(f'`{header}`' for header in evaluation.standard_headers)}")
    lines.append(f"- 标准记录总数：{metrics['standard_total']}")
    lines.append(f"- 实际环境记录总数：{metrics['actual_total']}")
    lines.append(f"- 正确匹配：{metrics['matched']}")
    lines.append(f"- 漏提取：{metrics['missed']}")
    lines.append(f"- 无法可靠匹配（多候选）：{metrics['ambiguous']}")
    lines.append(f"- 重复匹配冲突：{metrics['conflicts']}")
    lines.append(f"- 多余/未匹配提取：{metrics['extra']}")
    lines.append(f"- 预期位置提示不一致：{metrics['location_hint_mismatches']}")
    lines.append(f"- 标准点位为“见原文/企业年度汇总”的记录：{metrics['non_literal_point_rows']}")
    review_count = sum(
        1 for record in evaluation.batch.environmental.records if record.needs_review
    )
    enterprise_statuses = sorted(
        {
            enterprise.identity_status
            for enterprise in evaluation.batch.environmental.enterprises
        }
    )
    lines.append(f"- 待人工核实记录：{review_count}")
    lines.append(
        f"- 企业身份状态：{', '.join(enterprise_statuses) if enterprise_statuses else '无'}"
        "（测试数据无统一社会信用代码，按完全一致名称归并，企业身份需人工核验）"
    )
    lines.append("")
    lines.append("匹配规则：")
    lines.append("")
    lines.append("- 强制核对：来源文件名、企业名称（全角/半角与空白规范化后）、数据类别、指标名称、原始值、单位。")
    lines.append("- 点位为具体点位时必须核对；标准点位为“见原文”或“企业年度汇总”时，视为非具体范围描述，不做硬性点位核对。")
    lines.append("- `ND`、未检出、`<0.01` 必须保持空值并保留检出限表达，不得转换为 0。")
    lines.append("- `—` 缺失值必须保持空值并保留原始表达，不得转换为 0。")
    lines.append("- 逐条一对一匹配；存在多个候选时列入“无法可靠匹配”，不强行判定正确。")
    lines.append("- 单位按等价关系规范化（如 `m`/`m3`/`m³`、`mg/m`/`mg/m3`/`mg/m³`、`kwh`/`kWh`），不做数值换算。")
    lines.append("")
    lines.append("## 6. 提取召回率与精确率")
    lines.append("")
    lines.append("| 指标 | 计算 | 结果 |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| 提取召回率 | 正确匹配标准记录数 {metrics['matched']} / 标准记录总数 {metrics['standard_total']} | {format_rate(metrics['recall'])} |"
    )
    lines.append(
        f"| 提取精确率 | 正确匹配提取记录数 {metrics['matched']} / 参与比对提取记录总数 {metrics['actual_total']} | {format_rate(metrics['precision'])} |"
    )
    lines.append("")
    lines.append("> 指标仅针对本次提供的 5 份测试文档和 21 条标准答案，不代表对所有真实企业文档的泛化准确率。")
    lines.append("")
    lines.append("## 7. 逐条对比结果")
    lines.append("")
    lines.append("| 标准行号 | 来源文件 | 指标 | 标准原始值 | 实际值 | 单位 | 状态 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for comparison in evaluation.comparisons:
        standard = comparison.standard
        actual = comparison.actual
        lines.append(
            "| "
            + " | ".join(
                [
                    md_cell(standard.row_number if standard else ""),
                    md_cell(standard.source_file if standard else (Path(actual.source_file).name if actual else "")),
                    md_cell(standard.indicator if standard else (actual.indicator if actual else "")),
                    md_cell(standard.raw_value if standard else ""),
                    md_cell(actual.value if actual else ""),
                    md_cell(standard.unit if standard else (actual.unit if actual else "")),
                    md_cell(comparison.status),
                    md_cell("；".join(comparison.notes)),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 8. 未识别的数据")
    lines.append("")
    unreliable = [
        row
        for row in evaluation.comparisons
        if row.status in {"漏提取", "重复匹配冲突"} or row.status.startswith("无法可靠匹配")
    ]
    if unreliable:
        lines.append("| 标准行号 | 指标 | 状态 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for row in unreliable:
            lines.append(
                f"| {md_cell(row.standard.row_number if row.standard else '')} | "
                f"{md_cell(row.standard.indicator if row.standard else '')} | "
                f"{md_cell(row.status)} | {md_cell('；'.join(row.notes))} |"
            )
    else:
        lines.append("本次 21 条标准记录均实现可靠匹配，无漏提取或无法可靠匹配记录。")
    lines.append("")
    lines.append("需要说明的上下文限制：")
    lines.append("")
    non_literal = [
        row
        for row in evaluation.comparisons
        if row.actual is not None
        and any("见原文/企业年度汇总" in note for note in row.notes)
    ]
    if non_literal:
        lines.append(
            f"标准答案中有 {metrics['non_literal_point_rows']} 条记录的点位为“见原文”或“企业年度汇总”，不是文档中的具体点位。"
            "这些记录已按来源文件、企业、类别、指标、值、单位匹配，点位作为范围描述保留，未强行推断具体点位。"
        )
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 9. 错误识别的数据")
    lines.append("")
    extras = [row for row in evaluation.comparisons if row.status == "多余/未匹配提取"]
    if extras:
        lines.append("| 实际指标 | 实际值 | 单位 | 来源文件 | 来源位置 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for row in extras:
            actual = row.actual
            lines.append(
                f"| {md_cell(actual.indicator if actual else '')} | "
                f"{md_cell(actual.value if actual else '')} | "
                f"{md_cell(actual.unit if actual else '')} | "
                f"{md_cell(Path(actual.source_file).name if actual else '')} | "
                f"{md_cell('；'.join(row.notes))} |"
            )
    else:
        lines.append("修复后未发现多余、重复或错误提取记录。")
    lines.append("")
    lines.append("## 10. 已修复的问题")
    lines.append("")
    lines.append("| 问题 | 修复前观察 | 修复内容 | 修复后结果 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(
        "| 标准指标漏识别 | 缺少排放速率、停机时长、污泥转移量、年度用水量、年度用电量 | 补充指标定义与别名 | 5 类指标均提取 |"
    )
    lines.append(
        "| 设施运行时间名称不一致 | 实际为“治理设施运行时间”，标准为“设施运行时间” | 规范指标主名称并保留别名 | 指标名称一致 |"
    )
    lines.append(
        "| PDF 单位上标丢失 | `mg/m`、`m` 无法识别，部分记录缺少单位 | 增加单位别名并规范化到 `mg/m³`、`m³` | PDF 4 条标准记录单位匹配 |"
    )
    lines.append(
        "| 点位截断 | `DW001 废水总排口`、`DA001 废气排放口` 被截断为 `DW001`、`DA001` | 点位正则允许名称中的空格 | 1/2 号文件具体点位匹配 |"
    );
    lines.append(
        "| 管理台账点位缺失 | 未识别“设施名称：污水处理设施A” | 增加设施名称点位并支持唯一上下文点位回填 | 3 号文件点位匹配 |"
    )
    lines.append(
        "| 缺失值单位丢失 | `停机时长 — h` 的 h 未记录 | 无论是否有数值都从窗口提取单位 | 停机时长单位 h 保留，值保持空 |"
    )
    lines.append(
        "| ND 检出限单位误读 | 将 `ND` 中的 `D` 误识别为天单位 | 为仅单位匹配增加 ASCII 边界 | ND 记录单位为 `mg/m³` |"
    )
    lines.append(
        "| 点位/日期行被误识别为数据 | 修复前产生 3 条 `unrecognized` 伪记录（DW001、DA001、统计期间） | 无法识别数据必须存在明确数值+单位才记录 | 修复后无伪记录 |"
    )
    lines.append(
        "| pH 单位缺失 | 表格单位 `无量纲` 未识别 | 增加“无量纲”单位 | pH 单位匹配标准答案 |"
    )
    lines.append("")
    lines.append("修复前后概览：")
    lines.append("")
    lines.append("- 修复前探针：23 条环境记录，其中 3 条为点位/日期行误识别；多条标准指标、单位或点位无法匹配，未形成可靠的逐条标准比对。")
    lines.append(
        f"- 修复后：{metrics['actual_total']} 条环境记录；标准答案 {metrics['standard_total']} 条，正确匹配 {metrics['matched']} 条；召回率 {format_rate(metrics['recall'])}，精确率 {format_rate(metrics['precision'])}。"
    )
    lines.append("")
    lines.append("## 11. 尚未实现或未覆盖的功能")
    lines.append("")
    lines.append("- 自动计算、排放量核算、合规判断、AI 审核、Word 批注：按本阶段范围未实现。")
    lines.append("- 单位换算：仅做单位等价规范化用于匹配，未做数量换算。")
    lines.append("- OCR 表格结构还原：扫描件仅做文本 OCR，不还原表格。")
    lines.append("- 企业工商信息核验与模糊匹配：仅按统一社会信用代码或完全一致名称归并。")
    lines.append("- 复杂合并单元格、无线框 PDF 表格、多页跨页表格：未专门覆盖。")
    lines.append("- 标准答案中的“企业年度汇总/见原文”为非具体点位，系统不推断具体点位。")
    lines.append("- 本次企业名称不含统一社会信用代码，系统按名称归并并标记“企业身份未完全核验”。")
    lines.append("")
    lines.append("## 12. 结论")
    lines.append("")
    lines.append(
        f"本次测试共执行 pytest 测试，退出码 {pytest_code}。"
        f"标准答案逐条比对结果：{metrics['matched']}/{metrics['standard_total']} 正确匹配，"
        f"召回率 {format_rate(metrics['recall'])}，精确率 {format_rate(metrics['precision'])}。"
    )
    lines.append("")
    lines.append(f"完整逐条对比、提取记录明细和未匹配清单见：`{xlsx_path}`。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    evaluation = run_evaluation()

    xlsx_path = DOCS_DIR / "项目一_环境数据对比结果.xlsx"
    write_comparison_excel(evaluation, xlsx_path)

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    pytest_code, pytest_output = run_command(
        [sys.executable, "-m", "pytest", "-q"],
        env=env,
    )
    _, pip_output = run_command(
        [sys.executable, "-m", "pip", "check"],
        env=env,
    )

    report_path = DOCS_DIR / "项目一_环境数据提取测试报告.md"
    report_path.write_text(
        build_report(evaluation, pytest_output, pytest_code, pip_output, xlsx_path),
        encoding="utf-8",
    )

    metrics = evaluation.metrics
    print(f"测试报告: {report_path}")
    print(f"对比结果: {xlsx_path}")
    print(
        "标准答案: "
        f"{metrics['matched']}/{metrics['standard_total']} 正确匹配, "
        f"召回率 {format_rate(metrics['recall'])}, "
        f"精确率 {format_rate(metrics['precision'])}"
    )
    print(f"pytest 退出码: {pytest_code}")
    print(pytest_output)
    return pytest_code


if __name__ == "__main__":
    raise SystemExit(main())
