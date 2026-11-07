from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from docx import Document
from docx.document import Document as DocumentClass
from word_audit import word_annotator
from word_audit.annotation_common import build_comment_text
from word_audit.models import (
    LOCATION_LOCATED,
    VERIFICATION_VERIFIED,
    AuditIssue,
    CalculationInfo,
    LocationResult,
    SourceLocation,
)
from word_audit.project1_batch import DocumentView, Project1Batch
from word_audit.word_annotator import annotate_word_document
from word_audit.word_comments import (
    STATUS_FAILED,
    NativeCommentResult,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_read(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def _comments(path: Path) -> list[ElementTree.Element]:
    root = ElementTree.fromstring(_zip_read(path, "word/comments.xml"))
    return list(root.findall(f"{W}comment"))


def _comment_by_id(path: Path, comment_id: int) -> ElementTree.Element:
    identifier = str(comment_id)
    matches = [
        comment
        for comment in _comments(path)
        if comment.get(f"{W}id") == identifier
    ]
    assert len(matches) == 1
    return matches[0]


def _comment_paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{W}t":
            parts.append(element.text or "")
        elif element.tag == f"{W}tab":
            parts.append("\t")
        elif element.tag == f"{W}br":
            parts.append("\n")
    return "".join(parts)


def _comment_text(comment: ElementTree.Element) -> str:
    paragraphs = comment.findall(f"{W}p")
    return "\n".join(
        _comment_paragraph_text(paragraph) for paragraph in paragraphs
    )


def _marker_counts(path: Path, comment_id: int) -> tuple[int, int, int]:
    document_xml = _zip_read(path, "word/document.xml")
    root = ElementTree.fromstring(document_xml)
    identifier = str(comment_id)
    starts = [
        element
        for element in root.iter(f"{W}commentRangeStart")
        if element.get(f"{W}id") == identifier
    ]
    ends = [
        element
        for element in root.iter(f"{W}commentRangeEnd")
        if element.get(f"{W}id") == identifier
    ]
    references = [
        element
        for element in root.iter(f"{W}commentReference")
        if element.get(f"{W}id") == identifier
    ]
    return len(starts), len(ends), len(references)


def _comment_range_text(path: Path, comment_id: int) -> str:
    document_xml = _zip_read(path, "word/document.xml")
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


def _assert_native_comment(
    path: Path,
    *,
    comment_id: int,
    comment_text: str,
    anchor_text: str,
) -> None:
    comment = _comment_by_id(path, comment_id)
    assert _comment_text(comment) == comment_text
    assert comment.get(f"{W}author") == "DocumentAuditSystem"
    assert comment.get(f"{W}initials") == "DAS"
    assert _marker_counts(path, comment_id) == (1, 1, 1)
    assert _comment_range_text(path, comment_id) == anchor_text


def _table_snapshot(tables) -> list:
    snapshot = []
    for table in tables:
        rows = []
        for row in table.rows:
            rows.append(
                [
                    {
                        "text": cell.text,
                        "tables": _table_snapshot(cell.tables),
                    }
                    for cell in row.cells
                ]
            )
        snapshot.append(rows)
    return snapshot


def _assert_original_preserved(source: Path, output: Path) -> None:
    original = Document(str(source))
    annotated = Document(str(output))
    assert [p.text for p in annotated.paragraphs] == [
        p.text for p in original.paragraphs
    ]
    assert not any(p.text.startswith("#") for p in annotated.paragraphs)
    assert _table_snapshot(annotated.tables) == _table_snapshot(original.tables)


def _document_view(source: Path, document_id: str = "doc-1") -> DocumentView:
    return DocumentView(
        document_id=document_id,
        source_name=source.name,
        source_file=str(source),
        file_type="word",
        records=[],
        metadata={},
        tables=[],
    )


def _batch(document: DocumentView) -> Project1Batch:
    return Project1Batch(
        batch_id="native-writer-batch",
        schema_version="1.0",
        extracted_at=None,
        documents=[document],
        environmental_records=[],
        environmental={},
        path=Path("batch.json"),
        metadata={},
        environmental_present=True,
    )


def _source(
    path: Path,
    *,
    document_id: str = "doc-1",
    paragraph_index: int | None = None,
    table_index: int | None = None,
    row_index: int | None = None,
    column_index: int | None = None,
    value_row_index: int | None = None,
    value_column_index: int | None = None,
) -> SourceLocation:
    return SourceLocation(
        document_id=document_id,
        source_file=str(path),
        source_name=path.name,
        file_type="word",
        paragraph_index=paragraph_index,
        table_index=table_index,
        row_index=row_index,
        column_index=column_index,
        value_row_index=value_row_index,
        value_column_index=value_column_index,
        source_content_type="table" if table_index is not None else "paragraph",
        locator_method="table_cell" if table_index is not None else "exact_index",
        locator_confidence=0.95,
    )


def _location(issue: AuditIssue, source: SourceLocation) -> LocationResult:
    return LocationResult(
        issue_id=issue.issue_id,
        document_id=source.document_id,
        file_type="word",
        locator_status=LOCATION_LOCATED,
        paragraph_index=source.paragraph_index,
        table_index=source.table_index,
        row_index=source.row_index,
        column_index=source.column_index,
        locator_confidence=0.95,
        needs_manual_review=False,
        source_location=source,
    )


def _issue(
    issue_id: str,
    source: SourceLocation,
    original_text: str,
    *,
    issue_type: str = "other",
    calculation: CalculationInfo | None = None,
    metadata: dict | None = None,
    needs_manual_review: bool = False,
) -> AuditIssue:
    return AuditIssue(
        issue_id=issue_id,
        issue_type=issue_type,
        description="native writer test",
        original_text=original_text,
        location=source,
        calculation=calculation,
        needs_manual_review=needs_manual_review,
        metadata=dict(metadata or {}),
    )


def _calculation(
    *,
    reported_value: float = 85,
    computed_value: float = 70.5,
) -> CalculationInfo:
    return CalculationInfo(
        formula="100-15",
        reported_value=reported_value,
        computed_value=computed_value,
        unit="mg/L",
        verification_status=VERIFICATION_VERIFIED,
        verification_method="test",
    )


def _write_body(tmp_path: Path, text: str, name: str = "source.docx") -> Path:
    source = tmp_path / name
    document = Document()
    document.add_paragraph(text)
    document.save(source)
    return source


def _write_table(
    tmp_path: Path,
    rows: list[list[str]],
    name: str = "source.docx",
) -> Path:
    source = tmp_path / name
    document = Document()
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    for row_index, values in enumerate(rows):
        for column_index, value in enumerate(values):
            table.cell(row_index, column_index).text = value
    document.save(source)
    return source


def _write_with_existing_comment(tmp_path: Path) -> tuple[Path, int]:
    source = tmp_path / "existing.docx"
    document = Document()
    paragraph = document.add_paragraph()
    first_run = paragraph.add_run("COD")
    paragraph.add_run(" 85")
    comment = document.add_comment(
        [first_run],
        text="原始批注",
        author="DocumentAuditSystem",
        initials="DAS",
    )
    document.save(source)
    return source, int(comment.comment_id)


def test_body_native_comment_success(tmp_path) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "body",
        _source(source, paragraph_index=0),
        "85",
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation.status == "applied"
    assert annotation.comment_text == build_comment_text(issue)
    assert annotation.metadata["annotation_kind"] == "word_native_comment"
    assert annotation.metadata["anchor_text"] == "85"
    assert annotation.metadata["anchor_strategy"] == "body_exact"
    assert annotation.metadata["position"]["body_paragraph_index"] == 0
    assert annotation.word_anchor is not None
    assert annotation.word_anchor["insertion"] == "native_comment"
    assert annotation.word_anchor["paragraph_index"] == 0
    assert annotation.word_anchor["anchor_text"] == "85"
    assert annotation.word_anchor["occurrence_index"] == 0
    assert annotation.word_anchor["comment_id"] == annotation.metadata["comment_id"]
    assert output is not None
    assert output.is_file()
    assert _sha256(source) == source_hash
    _assert_native_comment(
        output,
        comment_id=annotation.metadata["comment_id"],
        comment_text=annotation.comment_text,
        anchor_text="85",
    )
    _assert_original_preserved(source, output)
    assert Document(str(output)).paragraphs[0].text == "COD 85 mg/L"


def test_table_cell_native_comment_success(tmp_path) -> None:
    source = _write_table(
        tmp_path,
        [["项目", "监测结果"], ["COD", "85 mg/L"]],
    )
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "table",
        _source(
            source,
            table_index=0,
            row_index=1,
            column_index=1,
        ),
        "85",
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation.status == "applied"
    assert annotation.word_anchor is not None
    assert annotation.word_anchor["table_index"] == 0
    assert annotation.word_anchor["row_index"] == 1
    assert annotation.word_anchor["column_index"] == 1
    assert annotation.word_anchor["table_cells"] == [
        {"table_index": 0, "row_index": 1, "cell_index": 1}
    ]
    assert output is not None
    assert _sha256(source) == source_hash
    _assert_native_comment(
        output,
        comment_id=annotation.metadata["comment_id"],
        comment_text=annotation.comment_text,
        anchor_text="85",
    )
    _assert_original_preserved(source, output)


def test_same_paragraph_two_non_overlapping_comments(tmp_path) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    document = _document_view(source)
    batch = _batch(document)
    first_issue = _issue(
        "first",
        _source(source, paragraph_index=0),
        "COD",
    )
    second_issue = _issue(
        "second",
        _source(source, paragraph_index=0),
        "85",
    )
    items = [
        (first_issue, _location(first_issue, first_issue.location)),
        (second_issue, _location(second_issue, second_issue.location)),
    ]

    annotations, output = annotate_word_document(
        batch,
        document,
        items,
        tmp_path / "annotated",
    )

    assert [annotation.status for annotation in annotations] == [
        "applied",
        "applied",
    ]
    first_id = annotations[0].metadata["comment_id"]
    second_id = annotations[1].metadata["comment_id"]
    assert first_id != second_id
    assert output is not None
    _assert_native_comment(
        output,
        comment_id=first_id,
        comment_text=annotations[0].comment_text,
        anchor_text="COD",
    )
    _assert_native_comment(
        output,
        comment_id=second_id,
        comment_text=annotations[1].comment_text,
        anchor_text="85",
    )
    assert len(_comments(output)) == 2


def test_same_anchor_second_comment_is_skipped(tmp_path) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    document = _document_view(source)
    batch = _batch(document)
    first_issue = _issue(
        "first",
        _source(source, paragraph_index=0),
        "85",
    )
    second_issue = _issue(
        "second",
        _source(source, paragraph_index=0),
        "85",
    )
    items = [
        (first_issue, _location(first_issue, first_issue.location)),
        (second_issue, _location(second_issue, second_issue.location)),
    ]

    annotations, output = annotate_word_document(
        batch,
        document,
        items,
        tmp_path / "annotated",
    )

    assert annotations[0].status == "applied"
    assert annotations[1].status == "skipped"
    assert annotations[1].error == "overlapping_comment_range"
    assert annotations[1].metadata["manual_review"] is True
    assert output is not None
    assert len(_comments(output)) == 1


def test_overlapping_anchors_second_comment_is_skipped(tmp_path) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    document = _document_view(source)
    batch = _batch(document)
    first_issue = _issue(
        "first",
        _source(source, paragraph_index=0),
        "COD 85",
    )
    second_issue = _issue(
        "second",
        _source(source, paragraph_index=0),
        "85 mg/L",
    )
    items = [
        (first_issue, _location(first_issue, first_issue.location)),
        (second_issue, _location(second_issue, second_issue.location)),
    ]

    annotations, output = annotate_word_document(
        batch,
        document,
        items,
        tmp_path / "annotated",
    )

    assert annotations[0].status == "applied"
    assert annotations[1].status == "skipped"
    assert annotations[1].error in {
        "overlapping_comment_range",
        "existing_comment_range",
    }
    assert output is not None
    assert len(_comments(output)) == 1


def test_existing_comment_is_preserved(tmp_path) -> None:
    source, original_comment_id = _write_with_existing_comment(tmp_path)
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "new",
        _source(source, paragraph_index=0),
        "85",
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "applied"
    assert output is not None
    assert _sha256(source) == source_hash
    comments = _comments(output)
    assert len(comments) == 2
    assert original_comment_id in {
        int(comment.get(f"{W}id")) for comment in comments
    }
    original_comment = _comment_by_id(output, original_comment_id)
    assert _comment_text(original_comment) == "原始批注"
    _assert_native_comment(
        output,
        comment_id=annotations[0].metadata["comment_id"],
        comment_text=annotations[0].comment_text,
        anchor_text="85",
    )


def test_low_confidence_typo_is_not_annotated(tmp_path) -> None:
    source = _write_body(tmp_path, "数剧数据")
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "low-typo",
        _source(source, paragraph_index=0),
        "数剧",
        issue_type="typo",
        metadata={
            "audit_rule": "typo",
            "typo_confidence": "low",
            "auto_annotate": False,
        },
        needs_manual_review=True,
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "skipped"
    assert annotations[0].metadata["manual_review"] is True
    assert output is None


def test_math_anchors_reported_value_not_computed_value(tmp_path) -> None:
    source = _write_table(
        tmp_path,
        [["项目", "监测结果"], ["COD", "85 (70.5)"]],
    )
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "math",
        _source(
            source,
            table_index=0,
            row_index=1,
            column_index=0,
            value_row_index=1,
            value_column_index=1,
        ),
        "COD\t85\tmg/L",
        issue_type="calculation_error",
        calculation=_calculation(),
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "applied"
    assert annotations[0].metadata["anchor_text"] == "85"
    assert annotations[0].metadata["anchor_strategy"] == "math_value_cell"
    assert output is not None
    assert _sha256(source) == source_hash
    _assert_native_comment(
        output,
        comment_id=annotations[0].metadata["comment_id"],
        comment_text=annotations[0].comment_text,
        anchor_text="85",
    )
    assert "经计算为 70.5" in annotations[0].comment_text


def test_math_ambiguous_anchor_is_skipped(tmp_path) -> None:
    source = _write_table(
        tmp_path,
        [["项目", "监测结果"], ["COD", "85 / 85"]],
    )
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "math-ambiguous",
        _source(
            source,
            table_index=0,
            row_index=1,
            column_index=0,
            value_row_index=1,
            value_column_index=1,
        ),
        "COD\t85\tmg/L",
        issue_type="calculation_error",
        calculation=_calculation(),
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "skipped"
    assert annotations[0].metadata["manual_review"] is True
    assert annotations[0].error == "ambiguous_text_occurrence"
    assert output is None


def test_comment_write_failure_keeps_source_unchanged(
    tmp_path,
    monkeypatch,
) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "write-failure",
        _source(source, paragraph_index=0),
        "85",
    )
    location = _location(issue, issue.location)

    def _failed_comment(*args, **kwargs):
        return NativeCommentResult(
            STATUS_FAILED,
            "comment_creation_failed",
            error_detail="injected comment failure",
        )

    monkeypatch.setattr(
        word_annotator,
        "add_span_comment",
        _failed_comment,
    )

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "failed"
    assert annotations[0].error == "comment_creation_failed"
    assert annotations[0].metadata["error_detail"] == "injected comment failure"
    assert output is None
    assert _sha256(source) == source_hash


def test_save_failure_removes_incomplete_output(
    tmp_path,
    monkeypatch,
) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    source_hash = _sha256(source)
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "save-failure",
        _source(source, paragraph_index=0),
        "85",
    )
    location = _location(issue, issue.location)

    def _partial_save(self, path):
        Path(path).write_bytes(b"incomplete")
        raise RuntimeError("injected save failure")

    monkeypatch.setattr(DocumentClass, "save", _partial_save)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert annotations[0].status == "failed"
    assert annotations[0].error == "word_save_failed"
    assert annotations[0].metadata["error_detail"] == "injected save failure"
    assert output is None
    assert list((tmp_path / "annotated").glob("*.docx")) == []
    assert _sha256(source) == source_hash


def test_body_and_table_text_and_structure_are_preserved(tmp_path) -> None:
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("正文 COD 85 mg/L")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "项目"
    table.cell(0, 1).text = "监测结果"
    table.cell(1, 0).text = "COD"
    table.cell(1, 1).text = "85 mg/L"
    document.save(source)
    document_view = _document_view(source)
    batch = _batch(document_view)
    body_issue = _issue(
        "body-preserve",
        _source(source, paragraph_index=0),
        "85",
    )
    table_issue = _issue(
        "table-preserve",
        _source(source, table_index=0, row_index=1, column_index=1),
        "85",
    )
    items = [
        (body_issue, _location(body_issue, body_issue.location)),
        (table_issue, _location(table_issue, table_issue.location)),
    ]

    annotations, output = annotate_word_document(
        batch,
        document_view,
        items,
        tmp_path / "annotated",
    )

    assert [annotation.status for annotation in annotations] == [
        "applied",
        "applied",
    ]
    assert output is not None
    _assert_original_preserved(source, output)
    assert len(_comments(output)) == 2


def test_output_reopens_with_complete_comment_markup(tmp_path) -> None:
    source = _write_body(tmp_path, "COD 85 mg/L")
    document = _document_view(source)
    batch = _batch(document)
    issue = _issue(
        "reopen",
        _source(source, paragraph_index=0),
        "85",
    )
    location = _location(issue, issue.location)

    annotations, output = annotate_word_document(
        batch,
        document,
        [(issue, location)],
        tmp_path / "annotated",
    )

    assert output is not None
    reopened = Document(str(output))
    assert reopened.paragraphs[0].text == "COD 85 mg/L"
    comment_id = annotations[0].metadata["comment_id"]
    assert _marker_counts(output, comment_id) == (1, 1, 1)
    assert _comment_range_text(output, comment_id) == "85"
    assert "word/comments.xml" in zipfile.ZipFile(output).namelist()
