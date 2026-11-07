from __future__ import annotations

import hashlib
import zipfile
from xml.etree import ElementTree

import pytest
from docx import Document
from docx.document import Document as DocumentClass
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from word_audit import word_comments
from word_audit.word_comments import (
    COMMENT_AUTHOR,
    COMMENT_INITIALS,
    PARAGRAPH_KIND_BODY,
    PARAGRAPH_KIND_TABLE_CELL,
    REASON_AMBIGUOUS_TEXT,
    REASON_BREAK,
    REASON_COMMENT_CREATION_FAILED,
    REASON_COMMENT_ROLLBACK_FAILED,
    REASON_CONTENT_CONTROL,
    REASON_CR,
    REASON_CROSS_RUN,
    REASON_DRAWING,
    REASON_EMPTY_TEXT,
    REASON_EXISTING_COMMENT,
    REASON_FIELD,
    REASON_FOOTNOTE,
    REASON_HYPERLINK,
    REASON_OUTPUT_OVERWRITES_SOURCE,
    REASON_OVERLAPPING_COMMENT,
    REASON_PARAGRAPH_POSITION,
    REASON_SOURCE_OPEN_FAILED,
    REASON_TAB,
    REASON_TEXT_NOT_FOUND,
    REASON_UNSUPPORTED_RUN_CONTENT,
    REASON_UNSUPPORTED_TEXT,
    STATUS_AMBIGUOUS,
    STATUS_APPLIED,
    STATUS_FAILED,
    STATUS_LOCATED,
    STATUS_NOOP,
    STATUS_NOT_FOUND,
    STATUS_PREPARED,
    STATUS_SKIPPED,
    STATUS_SPLIT,
    STATUS_UNSUPPORTED,
    ParagraphPosition,
    TableCellPath,
    add_single_run_comment,
    add_span_comment,
    annotate_document_file,
    annotate_single_run_file,
    annotate_span_file,
    find_document_paragraph,
    index_paragraph,
    is_simple_text_run,
    iter_document_paragraphs,
    locate_text,
    paragraph_unsupported_reasons,
    prepare_text_span,
    run_unsupported_reasons,
    split_run,
)


def _new_paragraph(*run_texts: str):
    document = Document()
    paragraph = document.add_paragraph()
    runs = [paragraph.add_run(text) for text in run_texts]
    return document, paragraph, runs


def _append_hyperlink(paragraph, text: str) -> None:
    hyperlink = OxmlElement("w:hyperlink")
    run = OxmlElement("w:r")
    text_element = OxmlElement("w:t")
    text_element.text = text
    text_element.set(qn("xml:space"), "preserve")
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def test_single_run_text_index_and_locate() -> None:
    _, paragraph, _ = _new_paragraph("COD 85 mg/L")

    index = index_paragraph(paragraph)

    assert index.text == paragraph.text == "COD 85 mg/L"
    assert len(index.segments) == 1
    segment = index.segments[0]
    assert segment.start == 0
    assert segment.end == 11
    assert segment.safe_to_split is True

    location = locate_text(index, "85")
    assert location.status == STATUS_LOCATED
    assert location.start == 4
    assert location.end == 6
    assert location.first_segment_index == 0
    assert location.last_segment_index == 0
    assert location.start_offset == 4
    assert location.end_offset == 6


def test_cross_run_index_and_span_preparation() -> None:
    _, paragraph, runs = _new_paragraph("COD 8", "5 mg/L")
    runs[0].bold = True
    runs[1].italic = True
    before = paragraph.text

    index = index_paragraph(paragraph)
    assert [segment.text for segment in index.segments] == ["COD 8", "5 mg/L"]

    location = locate_text(index, "85")
    assert location.status == STATUS_LOCATED
    assert location.first_segment_index == 0
    assert location.last_segment_index == 1
    assert location.start_offset == 4
    assert location.end_offset == 1

    prepared = prepare_text_span(index, location)
    assert prepared.status == STATUS_PREPARED
    assert prepared.first_run is not None
    assert prepared.last_run is not None
    assert prepared.first_run.text == "8"
    assert prepared.last_run.text == "5"
    assert prepared.first_run.bold is True
    assert prepared.last_run.italic is True
    assert paragraph.text == before


def test_split_run_preserves_run_properties() -> None:
    _, paragraph, runs = _new_paragraph("ABCD")
    run = runs[0]
    run.bold = True
    run.italic = True
    run.font.size = Pt(14)
    run.font.name = "Arial"
    before = paragraph.text

    result = split_run(paragraph, run, 2)

    assert result.status == STATUS_SPLIT
    assert result.left is not None
    assert result.right is not None
    assert result.left.text == "AB"
    assert result.right.text == "CD"
    assert paragraph.text == before
    for part in (result.left, result.right):
        assert part.bold is True
        assert part.italic is True
        assert part.font.size == Pt(14)
        assert part.font.name == "Arial"


def test_split_run_boundary_is_noop() -> None:
    _, paragraph, runs = _new_paragraph("ABCD")
    run = runs[0]
    before_run_count = len(paragraph.runs)

    start_result = split_run(paragraph, run, 0)
    end_result = split_run(paragraph, run, len(run.text))

    assert start_result.status == STATUS_NOOP
    assert start_result.left is None
    assert start_result.right is run
    assert end_result.status == STATUS_NOOP
    assert end_result.left is run
    assert end_result.right is None
    assert len(paragraph.runs) == before_run_count
    assert paragraph.text == "ABCD"


def test_text_not_found() -> None:
    _, paragraph, _ = _new_paragraph("COD 85")
    index = index_paragraph(paragraph)

    location = locate_text(index, "不存在")

    assert location.status == STATUS_NOT_FOUND
    assert location.reason == REASON_TEXT_NOT_FOUND


def test_empty_text_and_empty_paragraph() -> None:
    _, paragraph, _ = _new_paragraph()
    index = index_paragraph(paragraph)

    assert index.text == ""
    assert index.segments == ()

    empty = locate_text(index, "")
    assert empty.status == STATUS_NOT_FOUND
    assert empty.reason == REASON_EMPTY_TEXT

    missing = locate_text(index, "COD")
    assert missing.status == STATUS_NOT_FOUND
    assert missing.reason == REASON_TEXT_NOT_FOUND


def test_duplicate_text_is_ambiguous_without_occurrence_index() -> None:
    _, paragraph, _ = _new_paragraph("COD COD")
    index = index_paragraph(paragraph)

    location = locate_text(index, "COD")
    assert location.status == STATUS_AMBIGUOUS
    assert location.reason == REASON_AMBIGUOUS_TEXT
    assert location.occurrence_count == 2
    assert location.occurrences == ((0, 3), (4, 7))

    second = locate_text(index, "COD", occurrence_index=1)
    assert second.status == STATUS_LOCATED
    assert second.start == 4
    assert second.end == 7

    missing = locate_text(index, "COD", occurrence_index=2)
    assert missing.status == STATUS_NOT_FOUND
    assert missing.reason == "occurrence_index_out_of_range"


def test_tab_and_break_runs_are_rejected() -> None:
    _, tab_paragraph, tab_runs = _new_paragraph("A")
    tab_run = tab_runs[0]
    tab_run.add_tab()
    tab_run.add_text("B")
    tab_index = index_paragraph(tab_paragraph)
    assert REASON_TAB in run_unsupported_reasons(tab_run)
    assert locate_text(tab_index, "A\tB").status == STATUS_UNSUPPORTED
    assert locate_text(tab_index, "A").status == STATUS_UNSUPPORTED

    _, break_paragraph, break_runs = _new_paragraph("A")
    break_run = break_runs[0]
    break_run.add_break()
    break_run.add_text("B")
    break_index = index_paragraph(break_paragraph)
    assert REASON_BREAK in run_unsupported_reasons(break_run)
    assert locate_text(break_index, "A\nB").status == STATUS_UNSUPPORTED


def test_complex_run_is_not_modified_by_split() -> None:
    _, paragraph, runs = _new_paragraph("A")
    run = runs[0]
    run.add_tab()
    run.add_text("B")
    before_xml = run._r.xml
    before_text = paragraph.text

    result = split_run(paragraph, run, 1)

    assert result.status == STATUS_UNSUPPORTED
    assert REASON_TAB in (result.reason or "")
    assert run._r.xml == before_xml
    assert paragraph.text == before_text


def test_cr_field_footnote_and_unsupported_text_are_rejected() -> None:
    cases = (
        ("w:cr", REASON_CR),
        ("w:fldChar", REASON_FIELD),
        ("w:footnoteReference", REASON_FOOTNOTE),
        ("w:noBreakHyphen", REASON_UNSUPPORTED_TEXT),
        ("w:lastRenderedPageBreak", REASON_UNSUPPORTED_RUN_CONTENT),
    )
    for tag, reason in cases:
        _, paragraph, runs = _new_paragraph("A")
        run = runs[0]
        run._r.append(OxmlElement(tag))

        assert reason in run_unsupported_reasons(run)
        assert is_simple_text_run(run) is False
        index = index_paragraph(paragraph)
        assert locate_text(index, "A").status == STATUS_UNSUPPORTED


def test_drawing_run_is_rejected() -> None:
    _, paragraph, runs = _new_paragraph("A")
    run = runs[0]
    run._r.append(OxmlElement("w:drawing"))

    assert REASON_DRAWING in run_unsupported_reasons(run)
    assert is_simple_text_run(run) is False
    index = index_paragraph(paragraph)
    assert locate_text(index, "A").status == STATUS_UNSUPPORTED


def test_hyperlink_text_is_rejected_but_normal_text_is_allowed() -> None:
    _, paragraph, _ = _new_paragraph("prefix ")
    _append_hyperlink(paragraph, "link")
    index = index_paragraph(paragraph)

    assert index.text == paragraph.text == "prefix link"
    prefix = locate_text(index, "prefix")
    assert prefix.status == STATUS_LOCATED

    link = locate_text(index, "link")
    assert link.status == STATUS_UNSUPPORTED
    assert REASON_HYPERLINK in (link.reason or "")


def test_content_control_and_comment_ranges_are_detected() -> None:
    _, sdt_paragraph, _ = _new_paragraph("text")
    sdt_paragraph._p.append(OxmlElement("w:sdt"))
    assert REASON_CONTENT_CONTROL in paragraph_unsupported_reasons(
        sdt_paragraph
    )
    sdt_index = index_paragraph(sdt_paragraph)
    assert locate_text(sdt_index, "text").status == STATUS_UNSUPPORTED

    _, comment_paragraph, _ = _new_paragraph("text")
    comment_paragraph._p.append(OxmlElement("w:commentRangeStart"))
    comment_paragraph._p.append(OxmlElement("w:commentRangeEnd"))
    assert REASON_EXISTING_COMMENT in paragraph_unsupported_reasons(
        comment_paragraph
    )
    comment_index = index_paragraph(comment_paragraph)
    assert locate_text(comment_index, "text").status == STATUS_UNSUPPORTED


def test_locate_text_result_can_prepare_single_run_span() -> None:
    _, paragraph, _ = _new_paragraph("COD 85 mg/L")
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")

    prepared = prepare_text_span(index, location)

    assert prepared.status == STATUS_PREPARED
    assert prepared.first_run is not None
    assert prepared.last_run is prepared.first_run
    assert prepared.first_run.text == "85"
    assert paragraph.text == "COD 85 mg/L"


def test_prepare_rejects_unsafe_or_non_located_result() -> None:
    _, paragraph, _ = _new_paragraph("COD 85")
    index = index_paragraph(paragraph)

    missing = locate_text(index, "XYZ")
    assert prepare_text_span(index, missing).status == STATUS_UNSUPPORTED

    located = locate_text(index, "85")
    other_index = index_paragraph(paragraph)
    assert prepare_text_span(other_index, located).status == STATUS_UNSUPPORTED


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CONTENT_TYPES = (
    "{http://schemas.openxmlformats.org/package/2006/content-types}"
)
RELATIONSHIPS = (
    "{http://schemas.openxmlformats.org/package/2006/relationships}"
)


def _write_single_paragraph_docx(tmp_path, text: str, name: str = "source.docx"):
    document = Document()
    document.add_paragraph(text)
    path = tmp_path / name
    document.save(path)
    return path


def _write_multi_run_docx(tmp_path, runs, name: str = "source.docx"):
    document = Document()
    paragraph = document.add_paragraph()
    for text in runs:
        paragraph.add_run(text)
    path = tmp_path / name
    document.save(path)
    return path


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zip_read(path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def _comment_range_text(document_xml: bytes, comment_id: int) -> str:
    root = ElementTree.fromstring(document_xml)
    inside = False
    parts: list[str] = []
    identifier = str(comment_id)
    for element in root.iter():
        if (
            element.tag == W + "commentRangeStart"
            and element.get(W + "id") == identifier
        ):
            inside = True
            continue
        if (
            element.tag == W + "commentRangeEnd"
            and element.get(W + "id") == identifier
        ):
            inside = False
            continue
        if inside and element.tag == W + "t":
            parts.append(element.text or "")
    return "".join(parts)


def _assert_marker_ids(document_xml: bytes, comment_id: int) -> None:
    root = ElementTree.fromstring(document_xml)
    identifier = str(comment_id)
    starts = [
        element
        for element in root.iter(W + "commentRangeStart")
        if element.get(W + "id") == identifier
    ]
    ends = [
        element
        for element in root.iter(W + "commentRangeEnd")
        if element.get(W + "id") == identifier
    ]
    references = [
        element
        for element in root.iter(W + "commentReference")
        if element.get(W + "id") == identifier
    ]
    assert len(starts) == 1
    assert len(ends) == 1
    assert len(references) == 1


def _assert_comment_part(
    output_path,
    comment_id: int,
    comment_text: str,
) -> None:
    comments_xml = _zip_read(output_path, "word/comments.xml")
    root = ElementTree.fromstring(comments_xml)
    comments = [
        element
        for element in root.iter(W + "comment")
        if element.get(W + "id") == str(comment_id)
    ]
    assert len(comments) == 1
    comment = comments[0]
    text = "".join(
        element.text or "" for element in comment.iter(W + "t")
    )
    assert text == comment_text
    assert comment.get(W + "author") == COMMENT_AUTHOR
    assert comment.get(W + "initials") == COMMENT_INITIALS


def _table_snapshot(tables):
    snapshot = []
    for table in tables:
        rows = []
        for row in table.rows:
            cells = []
            for cell in row.cells:
                cells.append(
                    {
                        "text": cell.text,
                        "tables": _table_snapshot(cell.tables),
                    }
                )
            rows.append(cells)
        snapshot.append(rows)
    return snapshot


def _assert_native_comment_file(
    source_path,
    output_path,
    *,
    comment_id: int,
    comment_text: str,
    anchor_text: str,
) -> None:
    source_document = Document(str(source_path))
    source_texts = [p.text for p in source_document.paragraphs]
    output_document = Document(str(output_path))
    output_texts = [p.text for p in output_document.paragraphs]
    assert len(output_texts) == len(source_texts)
    assert output_texts == source_texts
    assert _table_snapshot(output_document.tables) == _table_snapshot(
        source_document.tables
    )
    assert len(output_document.comments) == 1

    document_xml = _zip_read(output_path, "word/document.xml")
    assert _comment_range_text(document_xml, comment_id) == anchor_text
    _assert_marker_ids(document_xml, comment_id)
    _assert_comment_part(output_path, comment_id, comment_text)

    content_types = ElementTree.fromstring(
        _zip_read(output_path, "[Content_Types].xml")
    )
    assert any(
        override.get("PartName") == "/word/comments.xml"
        and "comments+xml" in (override.get("ContentType") or "")
        for override in content_types.iter(CONTENT_TYPES + "Override")
    )

    relationships = ElementTree.fromstring(
        _zip_read(output_path, "word/_rels/document.xml.rels")
    )
    assert any(
        (relationship.get("Type") or "").endswith("/comments")
        and relationship.get("Target") == "comments.xml"
        for relationship in relationships.iter(
            RELATIONSHIPS + "Relationship"
        )
    )


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("COD 85 mg/L", "85"),
        ("85 COD mg/L", "85"),
        ("COD mg/L 85", "85"),
        ("85", "85"),
    ],
)
def test_single_run_native_comment_positions(tmp_path, text, needle) -> None:
    source = _write_single_paragraph_docx(tmp_path, text)
    source_hash = _sha256(source)

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        needle,
        "请核对该数值",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    assert result.anchor_text == needle
    assert _sha256(source) == source_hash
    _assert_native_comment_file(
        source,
        result.output_path,
        comment_id=result.comment_id,
        comment_text="请核对该数值",
        anchor_text=needle,
    )


def test_duplicate_text_returns_ambiguous(tmp_path) -> None:
    source = _write_single_paragraph_docx(tmp_path, "COD COD")
    source_hash = _sha256(source)

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "COD",
        "请核对",
    )

    assert result.status == STATUS_SKIPPED
    assert result.reason == REASON_AMBIGUOUS_TEXT
    assert result.output_path is None
    assert _sha256(source) == source_hash


def test_cross_run_text_is_rejected(tmp_path) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("COD 8")
    paragraph.add_run("5 mg/L")
    source = tmp_path / "source.docx"
    document.save(source)

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "85",
        "请核对",
    )

    assert result.status == STATUS_SKIPPED
    assert result.reason == REASON_CROSS_RUN


def test_complex_run_is_skipped(tmp_path) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    run = paragraph.add_run("A")
    run.add_tab()
    run.add_text("B")
    source = tmp_path / "source.docx"
    document.save(source)

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "A\tB",
        "请核对",
    )

    assert result.status == STATUS_SKIPPED
    assert REASON_TAB in (result.reason or "")
    assert result.output_path is None


def test_invalid_source_returns_failed(tmp_path) -> None:
    source = tmp_path / "corrupt.docx"
    source.write_bytes(b"not a docx")

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "COD",
        "请核对",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == REASON_SOURCE_OPEN_FAILED
    assert result.output_path is None


def test_output_path_must_not_overwrite_source(tmp_path) -> None:
    source = _write_single_paragraph_docx(tmp_path, "COD 85")
    source_hash = _sha256(source)

    result = annotate_single_run_file(
        source,
        source,
        0,
        "85",
        "请核对",
    )

    assert result.status == STATUS_SKIPPED
    assert result.reason == REASON_OUTPUT_OVERWRITES_SOURCE
    assert _sha256(source) == source_hash


def test_comment_creation_failure_rolls_back_paragraph(
    monkeypatch,
) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    before_xml = paragraph._p.xml

    def _raise(*args, **kwargs):
        raise RuntimeError("comment failure")

    monkeypatch.setattr(DocumentClass, "add_comment", _raise)

    result = add_single_run_comment(
        document,
        index,
        location,
        "请核对",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == "comment_creation_failed"
    restored = document.paragraphs[0]
    assert restored.text == "COD 85"
    assert restored._p.xml == before_xml


def test_two_comments_have_distinct_ids(tmp_path) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85 mg/L")

    first_index = index_paragraph(paragraph)
    first_location = locate_text(first_index, "COD")
    first = add_single_run_comment(
        document,
        first_index,
        first_location,
        "第一条批注",
    )
    assert first.status == STATUS_APPLIED
    assert first.comment_id is not None

    second_index = index_paragraph(paragraph, include_existing_comments=False)
    second_location = locate_text(second_index, "85")
    second = add_single_run_comment(
        document,
        second_index,
        second_location,
        "第二条批注",
    )
    assert second.status == STATUS_APPLIED
    assert second.comment_id is not None
    assert second.comment_id != first.comment_id

    output = tmp_path / "two_comments.docx"
    document.save(output)

    reopened = Document(str(output))
    assert len(reopened.comments) == 2
    document_xml = _zip_read(output, "word/document.xml")
    assert _comment_range_text(document_xml, first.comment_id) == "COD"
    assert _comment_range_text(document_xml, second.comment_id) == "85"
    _assert_marker_ids(document_xml, first.comment_id)
    _assert_marker_ids(document_xml, second.comment_id)
    _assert_comment_part(output, first.comment_id, "第一条批注")
    _assert_comment_part(output, second.comment_id, "第二条批注")


def test_cross_two_runs_native_comment_file(tmp_path) -> None:
    source = _write_multi_run_docx(tmp_path, ["COD 8", "5 mg/L"])
    source_hash = _sha256(source)

    result = annotate_span_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "85",
        "跨两个 Run 的批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    assert result.anchor_text == "85"
    assert _sha256(source) == source_hash
    _assert_native_comment_file(
        source,
        result.output_path,
        comment_id=result.comment_id,
        comment_text="跨两个 Run 的批注",
        anchor_text="85",
    )


def test_cross_three_runs_native_comment_file(tmp_path) -> None:
    source = _write_multi_run_docx(tmp_path, ["85 ", "mg/", "L"])
    source_hash = _sha256(source)

    result = annotate_span_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "85 mg/L",
        "跨三个 Run 的批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    assert result.anchor_text == "85 mg/L"
    assert _sha256(source) == source_hash
    _assert_native_comment_file(
        source,
        result.output_path,
        comment_id=result.comment_id,
        comment_text="跨三个 Run 的批注",
        anchor_text="85 mg/L",
    )


def test_cross_run_formatting_is_preserved() -> None:
    document = Document()
    paragraph = document.add_paragraph()
    first = paragraph.add_run("COD ")
    middle = paragraph.add_run("85")
    last = paragraph.add_run(" mg/L")
    first.italic = True
    middle.bold = True
    last.font.size = Pt(13)
    last.font.color.rgb = RGBColor(0x12, 0x34, 0x56)
    before = paragraph.text

    index = index_paragraph(paragraph)
    location = locate_text(index, "85 mg/L")
    result = add_span_comment(
        document,
        index,
        location,
        "跨 Run 格式测试",
    )

    assert result.status == STATUS_APPLIED
    assert paragraph.text == before
    result_first = result.first_run
    result_last = result.last_run
    assert result_first is not None
    assert result_last is not None
    assert result_first.text + result_last.text == "85 mg/L"
    assert result_first.bold is True
    assert result_last.font.size == Pt(13)
    assert result_last.font.color.rgb == RGBColor(0x12, 0x34, 0x56)


def test_single_run_api_still_rejects_cross_run() -> None:
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("COD 8")
    paragraph.add_run("5 mg/L")
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    before = paragraph.text

    result = add_single_run_comment(
        document,
        index,
        location,
        "单 Run API",
    )

    assert result.status == STATUS_SKIPPED
    assert result.reason == REASON_CROSS_RUN
    assert paragraph.text == before


def test_overlapping_comment_is_skipped() -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85 mg/L")

    first_index = index_paragraph(paragraph)
    first_location = locate_text(first_index, "COD 85")
    first = add_span_comment(
        document,
        first_index,
        first_location,
        "第一条批注",
    )
    assert first.status == STATUS_APPLIED

    second_index = index_paragraph(paragraph, include_existing_comments=False)
    second_location = locate_text(second_index, "85")
    second = add_span_comment(
        document,
        second_index,
        second_location,
        "重叠批注",
    )

    assert second.status == STATUS_SKIPPED
    assert second.reason == REASON_OVERLAPPING_COMMENT
    assert paragraph.text == "COD 85 mg/L"
    assert len(document.comments) == 1


def test_cross_run_complex_run_is_rejected(tmp_path) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    simple = paragraph.add_run("COD 8")
    complex_run = paragraph.add_run("5")
    complex_run.add_tab()
    complex_run.add_text("mg/L")
    source = tmp_path / "source.docx"
    document.save(source)
    source_hash = _sha256(source)

    result = annotate_span_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "85",
        "复杂 Run 跨范围",
    )

    assert result.status == STATUS_SKIPPED
    assert REASON_TAB in (result.reason or "")
    assert result.output_path is None
    assert _sha256(source) == source_hash
    assert simple.text + complex_run.text == "COD 85\tmg/L"


def test_cross_run_comment_failure_rolls_back(
    monkeypatch,
) -> None:
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run("COD 8")
    paragraph.add_run("5 mg/L")
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    before_xml = paragraph._p.xml
    before_text = paragraph.text

    def _raise(*args, **kwargs):
        raise RuntimeError("comment failure")

    monkeypatch.setattr(DocumentClass, "add_comment", _raise)

    result = add_span_comment(
        document,
        index,
        location,
        "跨 Run 失败回滚",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == "comment_creation_failed"
    restored = document.paragraphs[0]
    assert restored.text == before_text
    assert restored._p.xml == before_xml


def _table_paragraphs(document):
    return [
        handle
        for handle in iter_document_paragraphs(document)
        if handle.position.is_table_paragraph
        and handle.paragraph.text.strip()
    ]


def _assert_comment_in_position(
    output_path,
    position: ParagraphPosition,
    comment_id: int,
    anchor_text: str,
) -> None:
    document = Document(str(output_path))
    paragraph = find_document_paragraph(document, position)
    assert paragraph is not None
    assert anchor_text in paragraph.text
    markers = [
        element
        for element in paragraph._p.xpath(".//w:commentRangeStart")
        if element.get(qn("w:id")) == str(comment_id)
    ]
    assert len(markers) == 1
    assert (
        _comment_range_text(_zip_read(output_path, "word/document.xml"), comment_id)
        == anchor_text
    )

    ancestors = []
    parent = paragraph._p.getparent()
    while parent is not None:
        ancestors.append(parent.tag)
        parent = parent.getparent()
    if position.is_table_paragraph:
        assert qn("w:tc") in ancestors
    else:
        assert qn("w:tc") not in ancestors
        assert qn("w:body") in ancestors


def test_body_table_and_empty_paragraph_traversal() -> None:
    document = Document()
    document.add_paragraph("body one")
    document.add_paragraph("")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "cell one"
    document.add_paragraph("body two")

    handles = list(iter_document_paragraphs(document))

    assert [handle.position.document_order for handle in handles] == list(
        range(len(handles))
    )
    body = [
        handle
        for handle in handles
        if handle.position.kind == PARAGRAPH_KIND_BODY
    ]
    assert [handle.paragraph.text for handle in body] == [
        "body one",
        "",
        "body two",
    ]
    assert [handle.position.body_paragraph_index for handle in body] == [0, 1, 2]
    for handle in handles:
        resolved = find_document_paragraph(document, handle.position)
        assert resolved is not None
        assert resolved._p is handle.paragraph._p
        assert resolved.text == handle.paragraph.text

    table_handles = _table_paragraphs(document)
    assert [handle.paragraph.text for handle in table_handles] == ["cell one"]
    assert table_handles[0].position.table_cells == (
        TableCellPath(table_index=0, row_index=0, cell_index=0),
    )


def test_cell_multiple_paragraphs_traversal() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "first"
    cell.add_paragraph("second")

    handles = _table_paragraphs(document)

    assert [handle.paragraph.text for handle in handles] == ["first", "second"]
    assert [handle.position.cell_paragraph_index for handle in handles] == [0, 1]
    assert handles[0].position.table_cells == handles[1].position.table_cells


def test_nested_table_paragraph_traversal() -> None:
    document = Document()
    outer = document.add_table(rows=1, cols=1)
    cell = outer.cell(0, 0)
    cell.paragraphs[0].text = "outer"
    nested = cell.add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "inner"

    handles = _table_paragraphs(document)

    assert [handle.paragraph.text for handle in handles] == ["outer", "inner"]
    assert len(handles[0].position.table_cells) == 1
    assert len(handles[1].position.table_cells) == 2
    assert handles[1].position.table_cells[1] == TableCellPath(0, 0, 0)
    resolved = find_document_paragraph(document, handles[1].position)
    assert resolved is not None
    assert resolved.text == "inner"


def test_horizontal_merge_cell_dedupe() -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "merged"
    table.cell(1, 0).text = "left"
    table.cell(1, 1).text = "right"
    table.cell(0, 0).merge(table.cell(0, 1))

    handles = _table_paragraphs(document)

    assert [handle.paragraph.text for handle in handles] == [
        "merged",
        "left",
        "right",
    ]
    assert len({id(handle.paragraph._p) for handle in handles}) == len(handles)


def test_vertical_merge_cell_dedupe() -> None:
    document = Document()
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "merged"
    table.cell(0, 1).text = "top-right"
    table.cell(1, 1).text = "bottom-right"
    table.cell(0, 0).merge(table.cell(1, 0))

    handles = _table_paragraphs(document)

    assert [handle.paragraph.text for handle in handles] == [
        "merged",
        "top-right",
        "bottom-right",
    ]
    assert len({id(handle.paragraph._p) for handle in handles}) == len(handles)


def test_same_text_in_different_cells_is_not_merged() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "same"
    table.cell(0, 1).text = "same"

    handles = _table_paragraphs(document)

    assert len(handles) == 2
    assert handles[0].paragraph._p is not handles[1].paragraph._p
    assert handles[0].position.table_cells != handles[1].position.table_cells


def test_table_cell_single_run_native_comment(tmp_path) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "COD 85 mg/L"
    position = _table_paragraphs(document)[0].position
    source = tmp_path / "source.docx"
    document.save(source)
    source_hash = _sha256(source)

    result = annotate_document_file(
        source,
        tmp_path / "annotated.docx",
        position,
        "85",
        "表格单元格批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    assert result.anchor_text == "85"
    assert _sha256(source) == source_hash
    _assert_native_comment_file(
        source,
        result.output_path,
        comment_id=result.comment_id,
        comment_text="表格单元格批注",
        anchor_text="85",
    )
    _assert_comment_in_position(
        result.output_path,
        position,
        result.comment_id,
        "85",
    )


def test_table_cell_cross_run_native_comment(tmp_path) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    paragraph = table.cell(0, 0).paragraphs[0]
    paragraph.add_run("COD 8")
    paragraph.add_run("5 mg/L")
    position = _table_paragraphs(document)[0].position
    source = tmp_path / "source.docx"
    document.save(source)

    result = annotate_document_file(
        source,
        tmp_path / "annotated.docx",
        position,
        "85",
        "表格跨 Run 批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    _assert_comment_in_position(
        result.output_path,
        position,
        result.comment_id,
        "85",
    )


def test_nested_table_native_comment(tmp_path) -> None:
    document = Document()
    outer = document.add_table(rows=1, cols=1)
    cell = outer.cell(0, 0)
    cell.paragraphs[0].text = "outer"
    nested = cell.add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "inner 85"
    position = next(
        handle.position
        for handle in _table_paragraphs(document)
        if handle.paragraph.text == "inner 85"
    )
    source = tmp_path / "source.docx"
    document.save(source)

    result = annotate_document_file(
        source,
        tmp_path / "annotated.docx",
        position,
        "85",
        "嵌套表格批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    _assert_comment_in_position(
        result.output_path,
        position,
        result.comment_id,
        "85",
    )


def test_body_and_table_can_be_annotated_together(tmp_path) -> None:
    document = Document()
    document.add_paragraph("COD 85")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "氨氮 12.5"
    body_handle = next(
        handle
        for handle in iter_document_paragraphs(document)
        if handle.position.kind == PARAGRAPH_KIND_BODY
        and handle.paragraph.text == "COD 85"
    )
    table_handle = _table_paragraphs(document)[0]

    body_index = index_paragraph(body_handle.paragraph)
    body_location = locate_text(body_index, "85")
    body_result = add_span_comment(
        document,
        body_index,
        body_location,
        "正文批注",
    )
    table_index = index_paragraph(table_handle.paragraph)
    table_location = locate_text(table_index, "12.5")
    table_result = add_span_comment(
        document,
        table_index,
        table_location,
        "表格批注",
    )

    assert body_result.status == STATUS_APPLIED
    assert table_result.status == STATUS_APPLIED
    assert body_result.comment_id != table_result.comment_id

    output = tmp_path / "annotated.docx"
    document.save(output)
    reopened = Document(str(output))
    assert len(reopened.comments) == 2
    _assert_comment_in_position(
        output,
        body_handle.position,
        body_result.comment_id,
        "85",
    )
    _assert_comment_in_position(
        output,
        table_handle.position,
        table_result.comment_id,
        "12.5",
    )


def test_same_cell_different_paragraphs_can_be_annotated(tmp_path) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "COD 85"
    cell.add_paragraph("氨氮 12.5")
    handles = _table_paragraphs(document)
    assert len(handles) == 2

    first_index = index_paragraph(handles[0].paragraph)
    first_location = locate_text(first_index, "85")
    first = add_span_comment(
        document,
        first_index,
        first_location,
        "第一段批注",
    )
    second_index = index_paragraph(handles[1].paragraph)
    second_location = locate_text(second_index, "12.5")
    second = add_span_comment(
        document,
        second_index,
        second_location,
        "第二段批注",
    )

    assert first.status == STATUS_APPLIED
    assert second.status == STATUS_APPLIED
    assert first.comment_id != second.comment_id

    output = tmp_path / "annotated.docx"
    document.save(output)
    reopened_cell = Document(str(output)).tables[0].cell(0, 0)
    assert len(reopened_cell.paragraphs) == 2
    assert [p.text for p in reopened_cell.paragraphs] == ["COD 85", "氨氮 12.5"]
    _assert_comment_in_position(
        output,
        handles[0].position,
        first.comment_id,
        "85",
    )
    _assert_comment_in_position(
        output,
        handles[1].position,
        second.comment_id,
        "12.5",
    )


def test_table_overlapping_comment_is_skipped() -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "COD 85 mg/L"
    paragraph = _table_paragraphs(document)[0].paragraph

    first_index = index_paragraph(paragraph)
    first_location = locate_text(first_index, "COD 85")
    first = add_span_comment(
        document,
        first_index,
        first_location,
        "第一条批注",
    )
    assert first.status == STATUS_APPLIED

    second_index = index_paragraph(
        paragraph,
        include_existing_comments=False,
    )
    second_location = locate_text(second_index, "85")
    second = add_span_comment(
        document,
        second_index,
        second_location,
        "重叠批注",
    )

    assert second.status == STATUS_SKIPPED
    assert second.reason == REASON_OVERLAPPING_COMMENT
    assert len(document.comments) == 1


def test_later_comment_failure_does_not_break_previous(
    monkeypatch,
) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "COD 85"
    table.cell(0, 1).text = "氨氮 12.5"
    handles = _table_paragraphs(document)

    first_index = index_paragraph(handles[0].paragraph)
    first_location = locate_text(first_index, "85")
    first = add_span_comment(
        document,
        first_index,
        first_location,
        "第一条批注",
    )
    assert first.status == STATUS_APPLIED

    second_index = index_paragraph(handles[1].paragraph)
    second_location = locate_text(second_index, "12.5")
    before_second_xml = handles[1].paragraph._p.xml

    def _raise(*args, **kwargs):
        raise RuntimeError("comment failure")

    monkeypatch.setattr(DocumentClass, "add_comment", _raise)
    second = add_span_comment(
        document,
        second_index,
        second_location,
        "第二条批注",
    )

    assert second.status == STATUS_FAILED
    restored = find_document_paragraph(document, handles[1].position)
    assert restored is not None
    assert restored._p.xml == before_second_xml
    assert len(document.comments) == 1
    assert first.comment_id is not None


def test_invalid_paragraph_position_is_skipped(tmp_path) -> None:
    document = Document()
    document.add_paragraph("COD 85")
    source = tmp_path / "source.docx"
    document.save(source)
    source_hash = _sha256(source)
    invalid = ParagraphPosition(
        kind=PARAGRAPH_KIND_TABLE_CELL,
        table_cells=(TableCellPath(99, 0, 0),),
    )

    result = annotate_document_file(
        source,
        tmp_path / "annotated.docx",
        invalid,
        "85",
        "无效位置",
    )

    assert result.status == STATUS_SKIPPED
    assert result.reason == REASON_PARAGRAPH_POSITION
    assert result.output_path is None
    assert _sha256(source) == source_hash


def _comments_part(document):
    try:
        return document.part.part_related_by(RT.COMMENTS)
    except KeyError:
        return None


def _comment_ids(document) -> set[int]:
    part = _comments_part(document)
    if part is None:
        return set()
    return {
        int(comment.get(qn("w:id")))
        for comment in part.element.xpath("./w:comment")
    }


def _comments_relationship_ids(document) -> set[str]:
    return {
        rel_id
        for rel_id, relationship in document.part.rels.items()
        if relationship.reltype == RT.COMMENTS
    }


def _zip_has_comments_relationship(path) -> bool:
    root = ElementTree.fromstring(
        _zip_read(path, "word/_rels/document.xml.rels")
    )
    return any(
        (relationship.get("Type") or "").endswith("/comments")
        for relationship in root
    )


def _document_with_existing_comment():
    document = Document()
    paragraph = document.add_paragraph()
    first_run = paragraph.add_run("COD")
    paragraph.add_run(" 85")
    comment = document.add_comment(
        [first_run],
        text="原始批注",
        author=COMMENT_AUTHOR,
        initials=COMMENT_INITIALS,
    )
    return document, paragraph, int(comment.comment_id)


def _raise_add_comment(*args, **kwargs):
    raise RuntimeError("add comment failed")


def _create_comments_part_then_raise(self, runs, text="", author="", initials=""):
    _ = self.part._comments_part
    raise RuntimeError("comments part created before failure")


def _partial_marker_stub(created_ids):
    def stub(self, runs, text="", author="", initials=""):
        comment = self.comments.add_comment(
            text=text,
            author=author,
            initials=initials,
        )
        created_ids.append(int(comment.comment_id))
        run_list = runs if isinstance(runs, (list, tuple)) else [runs]
        run_list[0]._r.insert_comment_range_start_above(comment.comment_id)
        raise RuntimeError("partial range marker written before failure")

    return stub


def _assert_no_comments_artifact(document, path) -> None:
    assert _comments_part(document) is None
    assert _comments_relationship_ids(document) == set()
    document.save(path)
    assert "word/comments.xml" not in zipfile.ZipFile(path).namelist()
    assert not _zip_has_comments_relationship(path)


def test_paragraph_position_body_roundtrip() -> None:
    position = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=3,
        document_order=7,
        text="正文段落",
    )

    data = position.to_dict()
    restored = ParagraphPosition.from_dict(data)

    assert restored == position
    assert restored.to_dict() == data


def test_paragraph_position_table_roundtrip() -> None:
    position = ParagraphPosition(
        kind=PARAGRAPH_KIND_TABLE_CELL,
        table_cells=(TableCellPath(table_index=1, row_index=2, cell_index=3),),
        cell_paragraph_index=2,
        document_order=9,
        text="表格段落",
    )

    data = position.to_dict()
    restored = ParagraphPosition.from_dict(data)

    assert restored == position
    assert restored.table_cells == (
        TableCellPath(table_index=1, row_index=2, cell_index=3),
    )
    assert restored.to_dict() == data


def test_paragraph_position_nested_table_roundtrip() -> None:
    position = ParagraphPosition(
        kind=PARAGRAPH_KIND_TABLE_CELL,
        table_cells=(
            TableCellPath(table_index=0, row_index=1, cell_index=2),
            TableCellPath(table_index=3, row_index=4, cell_index=5),
        ),
        cell_paragraph_index=1,
        document_order=12,
        text="嵌套表格段落",
    )

    data = position.to_dict()
    restored = ParagraphPosition.from_dict(data)

    assert restored == position
    assert isinstance(restored.table_cells, tuple)
    assert all(
        isinstance(cell, TableCellPath) for cell in restored.table_cells
    )
    assert restored.to_dict() == data


def test_paragraph_position_from_dict_rejects_missing_fields() -> None:
    data = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=0,
    ).to_dict()
    data.pop("text")

    with pytest.raises(ValueError, match="missing fields"):
        ParagraphPosition.from_dict(data)


def test_paragraph_position_from_dict_rejects_illegal_indices() -> None:
    data = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=0,
    ).to_dict()
    data["body_paragraph_index"] = -1

    with pytest.raises(ValueError, match="non-negative"):
        ParagraphPosition.from_dict(data)

    table_data = ParagraphPosition(
        kind=PARAGRAPH_KIND_TABLE_CELL,
        table_cells=(TableCellPath(0, 0, 0),),
    ).to_dict()
    table_data["table_cells"][0]["row_index"] = True

    with pytest.raises(TypeError, match="integer"):
        ParagraphPosition.from_dict(table_data)


def test_paragraph_position_from_dict_rejects_unknown_kind() -> None:
    data = ParagraphPosition(
        kind=PARAGRAPH_KIND_BODY,
        body_paragraph_index=0,
    ).to_dict()
    data["kind"] = "unknown"

    with pytest.raises(ValueError, match="unknown paragraph position kind"):
        ParagraphPosition.from_dict(data)


def test_paragraph_position_from_dict_rejects_table_cell_types() -> None:
    data = ParagraphPosition(
        kind=PARAGRAPH_KIND_TABLE_CELL,
        table_cells=(TableCellPath(0, 0, 0),),
    ).to_dict()
    data["table_cells"] = "not-a-list"

    with pytest.raises(TypeError, match="table_cells must be"):
        ParagraphPosition.from_dict(data)

    data["table_cells"] = ["not-a-dict"]

    with pytest.raises(TypeError, match="must be a dict"):
        ParagraphPosition.from_dict(data)


def test_transaction_first_comment_without_comments_part(tmp_path) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    assert _comments_part(document) is None

    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    result = add_single_run_comment(
        document,
        index,
        location,
        "首次批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.comment_id in _comment_ids(document)
    assert _comments_part(document) is not None

    output = tmp_path / "first.docx"
    document.save(output)
    assert "word/comments.xml" in zipfile.ZipFile(output).namelist()
    assert len(Document(str(output)).comments) == 1


def test_transaction_existing_comments_add_new_and_preserve_source(
    tmp_path,
) -> None:
    document, _, original_id = _document_with_existing_comment()
    source = tmp_path / "source.docx"
    document.save(source)
    source_hash = _sha256(source)

    result = annotate_single_run_file(
        source,
        tmp_path / "annotated.docx",
        0,
        "85",
        "新增批注",
    )

    assert result.status == STATUS_APPLIED
    assert result.output_path is not None
    assert result.comment_id is not None
    assert _sha256(source) == source_hash

    reopened = Document(str(result.output_path))
    assert len(reopened.comments) == 2
    assert {comment.comment_id for comment in reopened.comments} == {
        original_id,
        result.comment_id,
    }
    _assert_comment_part(result.output_path, original_id, "原始批注")
    _assert_comment_part(
        result.output_path,
        result.comment_id,
        "新增批注",
    )


def test_transaction_existing_comments_failure_preserves_original(
    monkeypatch,
    tmp_path,
) -> None:
    document, paragraph, original_id = _document_with_existing_comment()
    comments_part = _comments_part(document)
    assert comments_part is not None
    before_comments_xml = comments_part.element.xml
    before_comment_ids = _comment_ids(document)
    before_paragraph_xml = paragraph._p.xml
    before_text = paragraph.text

    monkeypatch.setattr(DocumentClass, "add_comment", _raise_add_comment)

    index = index_paragraph(paragraph, include_existing_comments=False)
    location = locate_text(index, "85")
    result = add_single_run_comment(
        document,
        index,
        location,
        "失败批注",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == REASON_COMMENT_CREATION_FAILED
    assert result.error_detail == "add comment failed"
    assert _comments_part(document) is comments_part
    assert comments_part.element.xml == before_comments_xml
    assert _comment_ids(document) == before_comment_ids == {original_id}

    restored = document.paragraphs[0]
    assert restored.text == before_text
    assert restored._p.xml == before_paragraph_xml

    output = tmp_path / "preserved.docx"
    document.save(output)
    reopened = Document(str(output))
    reopened_comments = list(reopened.comments)
    assert len(reopened_comments) == 1
    assert reopened_comments[0].comment_id == original_id


def test_transaction_comments_part_created_then_failure_is_cleaned(
    monkeypatch,
    tmp_path,
) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    before_paragraph_xml = paragraph._p.xml
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    monkeypatch.setattr(
        DocumentClass,
        "add_comment",
        _create_comments_part_then_raise,
    )

    result = add_single_run_comment(
        document,
        index,
        location,
        "失败批注",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == REASON_COMMENT_CREATION_FAILED
    assert "comments part created" in (result.error_detail or "")
    assert document.paragraphs[0]._p.xml == before_paragraph_xml
    _assert_no_comments_artifact(document, tmp_path / "cleaned.docx")


def test_transaction_partial_range_marker_is_rolled_back(
    monkeypatch,
    tmp_path,
) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    before_paragraph_xml = paragraph._p.xml
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    created_ids: list[int] = []
    monkeypatch.setattr(
        DocumentClass,
        "add_comment",
        _partial_marker_stub(created_ids),
    )

    result = add_single_run_comment(
        document,
        index,
        location,
        "失败批注",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == REASON_COMMENT_CREATION_FAILED
    assert created_ids
    restored = document.paragraphs[0]
    assert restored._p.xml == before_paragraph_xml
    marker_ids = {
        int(marker.get(qn("w:id")))
        for marker in restored._p.xpath(".//w:commentRangeStart")
    }
    assert created_ids[0] not in marker_ids
    _assert_no_comments_artifact(document, tmp_path / "cleaned.docx")


def test_transaction_first_success_second_failure_keeps_first(
    monkeypatch,
    tmp_path,
) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    first_index = index_paragraph(paragraph)
    first_location = locate_text(first_index, "COD")
    first = add_span_comment(
        document,
        first_index,
        first_location,
        "第一条批注",
    )
    assert first.status == STATUS_APPLIED

    first_ids = _comment_ids(document)
    first_comments_xml = _comments_part(document).element.xml
    second_index = index_paragraph(
        paragraph,
        include_existing_comments=False,
    )
    second_location = locate_text(second_index, "85")
    monkeypatch.setattr(DocumentClass, "add_comment", _raise_add_comment)
    second = add_span_comment(
        document,
        second_index,
        second_location,
        "第二条批注",
    )

    assert second.status == STATUS_FAILED
    assert second.reason == REASON_COMMENT_CREATION_FAILED
    assert _comment_ids(document) == first_ids
    assert _comments_part(document).element.xml == first_comments_xml

    restored = document.paragraphs[0]
    assert restored.text == "COD 85"
    marker_ids = {
        int(marker.get(qn("w:id")))
        for marker in restored._p.xpath(".//w:commentRangeStart")
    }
    assert marker_ids == {first.comment_id}

    output = tmp_path / "kept-first.docx"
    document.save(output)
    reopened = Document(str(output))
    reopened_comments = list(reopened.comments)
    assert len(reopened_comments) == 1
    assert reopened_comments[0].comment_id == first.comment_id


def test_transaction_table_structure_unchanged(
    monkeypatch,
    tmp_path,
) -> None:
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "COD 85"
    paragraph = table.cell(0, 0).paragraphs[0]
    before_tables = _table_snapshot(document.tables)
    before_paragraph_xml = paragraph._p.xml
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")
    created_ids: list[int] = []
    monkeypatch.setattr(
        DocumentClass,
        "add_comment",
        _partial_marker_stub(created_ids),
    )

    result = add_span_comment(
        document,
        index,
        location,
        "失败批注",
    )

    assert result.status == STATUS_FAILED
    assert created_ids
    assert _table_snapshot(document.tables) == before_tables
    restored = document.tables[0].cell(0, 0).paragraphs[0]
    assert restored._p.xml == before_paragraph_xml
    _assert_no_comments_artifact(document, tmp_path / "table.docx")

    reopened = Document(str(tmp_path / "table.docx"))
    assert reopened.tables[0].cell(0, 0).text == "COD 85"


def test_transaction_rollback_failure_is_reported(monkeypatch) -> None:
    document = Document()
    paragraph = document.add_paragraph("COD 85")
    index = index_paragraph(paragraph)
    location = locate_text(index, "85")

    monkeypatch.setattr(DocumentClass, "add_comment", _raise_add_comment)

    def _raise_restore(*args, **kwargs):
        raise RuntimeError("restore failed")

    monkeypatch.setattr(
        word_comments,
        "_restore_paragraph",
        _raise_restore,
    )

    result = add_single_run_comment(
        document,
        index,
        location,
        "失败批注",
    )

    assert result.status == STATUS_FAILED
    assert result.reason == REASON_COMMENT_ROLLBACK_FAILED
    assert "restore failed" in (result.error_detail or "")
