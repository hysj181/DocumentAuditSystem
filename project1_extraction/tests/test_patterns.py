from __future__ import annotations

from doc_extractor.core.patterns import extract_entities


def _by_type(text: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for entity in extract_entities(text):
        grouped.setdefault(entity.type, []).append(entity)
    return grouped


def test_detects_all_supported_entity_types() -> None:
    text = "整数 42，小数 3.14，金额 ￥1,234.56 和 500元，百分比 12.5%，日期 2024-05-01。"
    grouped = _by_type(text)

    assert [entity.value for entity in grouped["integer"]] == [42]
    assert [entity.value for entity in grouped["decimal"]] == [3.14]
    assert sorted(entity.value for entity in grouped["amount"]) == [500, 1234.56]
    assert [entity.value for entity in grouped["percentage"]] == [12.5]
    assert [entity.value for entity in grouped["date"]] == ["2024-05-01"]


def test_dates_are_not_counted_as_integers_or_decimals() -> None:
    grouped = _by_type("日期 2024/06/30 和 2024年7月1日")

    assert len(grouped["date"]) == 2
    assert "integer" not in grouped
    assert "decimal" not in grouped


def test_full_width_percentage_and_currency_are_supported() -> None:
    grouped = _by_type("占比 80％ 金额 ￥99.90 以及 3万元")

    assert grouped["percentage"][0].value == 80
    assert sorted(entity.value for entity in grouped["amount"]) == [99.9, 30000]


def test_formatted_decimal_without_currency_is_decimal() -> None:
    grouped = _by_type("数值 1,234.56")

    assert grouped["decimal"][0].value == 1234.56
    assert "amount" not in grouped


def test_full_width_digits_from_ocr_are_recognized() -> None:
    grouped = _by_type("合同金额 １２３４５．６７元，日期 ２０２４－０５－０１，比例 ８０％")

    assert grouped["amount"][0].value == 12345.67
    assert grouped["date"][0].value == "2024-05-01"
    assert grouped["percentage"][0].value == 80


def test_empty_text_returns_no_entities() -> None:
    assert extract_entities("") == []
