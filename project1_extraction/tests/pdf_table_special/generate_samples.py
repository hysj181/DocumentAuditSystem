from __future__ import annotations

import json
from pathlib import Path

from support import (
    BORDERLESS_ROWS,
    SPECIAL_ROWS,
    SPECIAL_STANDARD_ANSWERS,
    make_borderless_native_pdf,
    make_special_values_pdf,
    render_pdf_page_to_image_only_pdf,
)

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    bordered = make_special_values_pdf(SAMPLES_DIR / "bordered_special_values.pdf")
    borderless = make_borderless_native_pdf(SAMPLES_DIR / "borderless_native.pdf")
    scanned = render_pdf_page_to_image_only_pdf(
        bordered, SAMPLES_DIR / "scanned_special_values.pdf", dpi=200
    )
    standard = {
        "description": "项目一 PDF 表格专项模拟样本标准答案（独立于 test_data）",
        "samples": {
            "bordered_special_values.pdf": {
                "type": "native_pdf_bordered",
                "table": {
                    "rows": len(SPECIAL_ROWS),
                    "columns": 5,
                    "header": SPECIAL_ROWS[0],
                    "grid": SPECIAL_ROWS,
                },
                "environmental": SPECIAL_STANDARD_ANSWERS,
            },
            "scanned_special_values.pdf": {
                "type": "scanned_pdf",
                "source": "bordered_special_values.pdf",
                "expected_table_detection": "depends_on_engine",
                "environmental": SPECIAL_STANDARD_ANSWERS,
            },
            "borderless_native.pdf": {
                "type": "native_pdf_borderless",
                "table": {
                    "rows": len(BORDERLESS_ROWS),
                    "columns": 6,
                    "header": BORDERLESS_ROWS[0],
                    "grid": BORDERLESS_ROWS,
                },
                "known_limitation": "PyMuPDF 与 PP-StructureV3 在当前样本上均未检出无边框表格",
            },
        },
    }
    (SAMPLES_DIR / "standard_answers.json").write_text(
        json.dumps(standard, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("generated:")
    for path in (bordered, borderless, scanned, SAMPLES_DIR / "standard_answers.json"):
        print(path)


if __name__ == "__main__":
    main()
