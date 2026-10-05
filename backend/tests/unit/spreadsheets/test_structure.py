"""The constant-memory XML pre-scan that runs before openpyxl (reader.check_xlsx_structure).

openpyxl's memory grows 10 to 25 times faster than the inflated XML it parses (a 150 KB upload with one
two-million-cell row took 1.4 GB), so these files must be refused before openpyxl sees them. Most tests
lower the limits so the hostile files stay tiny.
"""

import io
import zipfile

import openpyxl
import pytest

from app.spreadsheets import reader
from app.spreadsheets.errors import DAMAGED_MESSAGE, TOO_COMPLEX_MESSAGE, FileTooLarge, UnsupportedFileType
from app.spreadsheets.inspect import inspect
from tests.unit.spreadsheets.workbooks import make_xlsx, rewrite_xlsx, sheet_xml

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SST_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
SST_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"
BASE = make_xlsx({"S": [["name", "amount"], ["ali", 12]]})


def part(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode()


def with_rows(rows_xml: str, data: bytes = BASE, name: str = "xl/worksheets/sheet1.xml") -> bytes:
    xml = sheet_xml(data)
    start, end = xml.index("<sheetData>"), xml.index("</sheetData>") + len("</sheetData>")
    return rewrite_xlsx(data, {name: xml[:start] + f"<sheetData>{rows_xml}</sheetData>" + xml[end:]})


def with_shared_strings(strings_xml: str, rows_xml: str) -> bytes:
    """BASE turned into the layout Excel writes: cells refer to a shared strings table."""
    data = with_rows(rows_xml)
    types = part(data, "[Content_Types].xml").replace(
        "</Types>", f'<Override PartName="/xl/sharedStrings.xml" ContentType="{SST_TYPE}"/></Types>'
    )
    rels = part(data, "xl/_rels/workbook.xml.rels").replace(
        "</Relationships>",
        f'<Relationship Id="rIdSST" Type="{SST_REL}" Target="sharedStrings.xml"/></Relationships>',
    )
    return rewrite_xlsx(
        data,
        {
            "[Content_Types].xml": types,
            "xl/_rels/workbook.xml.rels": rels,
            "xl/sharedStrings.xml": f'<sst xmlns="{MAIN}">{strings_xml}</sst>',
        },
    )


def refused(data: bytes) -> FileTooLarge | UnsupportedFileType:
    with pytest.raises((FileTooLarge, UnsupportedFileType)) as error:
        inspect(data, "xlsx")
    return error.value  # type: ignore[return-value]


@pytest.fixture
def no_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if a file reaches openpyxl: the scan must refuse it first."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("openpyxl was asked to parse a file the pre-scan should have refused")

    monkeypatch.setattr(openpyxl, "load_workbook", forbidden)


def test_shared_strings_workbooks_are_read() -> None:
    data = with_shared_strings(
        "<si><t>name</t></si><si><t>amount</t></si><si><t>علی</t></si><si><r><t>رض</t></r><r><t>ا</t></r></si>",
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>7</v></c></row>'
        '<row r="4"><c r="A4" t="s"><v>3</v></c><c r="B4"><v>8</v></c></row>',
    )
    sheet = inspect(data, "xlsx").sheets[0]
    assert [c.name for c in sheet.columns] == ["name", "amount"]
    assert [list(r.values()) for r in sheet.sample_rows] == [["علی", 7], ["رضا", 8]]


def test_the_measured_attack_is_refused_at_the_default_limits(no_openpyxl: None) -> None:
    # One row of 120,000 cells: about 3 MB of XML that deflates to a few kilobytes.
    data = with_rows('<row r="1">' + '<c r="A1" t="n"><v>1</v></c>' * 120_000 + "</row>")
    assert len(data) < 100_000
    error = refused(data)
    assert error.status == 413 and error.message_fa == TOO_COMPLEX_MESSAGE


def test_a_row_may_hold_a_bounded_number_of_elements(
    monkeypatch: pytest.MonkeyPatch, no_openpyxl: None
) -> None:
    monkeypatch.setattr(reader, "MAX_SUBTREE_ELEMENTS", 50)
    assert refused(with_rows('<row r="1">' + "<c><v>1</v></c>" * 30 + "</row>")).status == 413
    with pytest.raises(FileTooLarge):  # rich text runs inside one cell count too
        inspect(
            with_rows('<row r="1"><c t="inlineStr"><is>' + "<r><t>x</t></r>" * 30 + "</is></c></row>"), "xlsx"
        )


def test_elements_openpyxl_would_keep_are_capped(monkeypatch: pytest.MonkeyPatch, no_openpyxl: None) -> None:
    monkeypatch.setattr(reader, "MAX_RETAINED_ELEMENTS", 40)
    junk_in_rows_container = '<row r="1"><c><v>1</v></c></row>' + "<x/>" * 60
    assert refused(with_rows(junk_in_rows_container)).status == 413
    foreign_rows = (
        '<row r="1"><c><v>1</v></c></row>' + '<x:row xmlns:x="urn:other"/>' * 60
    )  # not openpyxl's row
    assert refused(with_rows(foreign_rows)).status == 413


@pytest.mark.parametrize(
    "rows",
    [
        '<row r="2"><c><v>1</v></c></row><row r="1"><c><v>2</v></c></row>',
        '<row r="1"><c><v>1</v></c></row>' + '<row r="1"/>' * 5,  # openpyxl would never stop reading
        '<row r="1.5"><c><v>1</v></c></row>',
        '<row r="x"><c><v>1</v></c></row>',
        '<row r="1"><row r="2"/></row>',
    ],
)
def test_row_numbers_must_increase(rows: str, no_openpyxl: None) -> None:
    error = refused(with_rows(rows))
    assert error.status in (413, 415)


def test_rows_without_numbers_count_up() -> None:
    data = with_rows(
        '<row><c t="inlineStr"><is><t>a</t></is></c></row>'
        '<row><c><v>1</v></c></row><row r="5"><c><v>2</v></c></row>'
    )
    assert inspect(data, "xlsx").sheets[0].rows == 2


@pytest.mark.parametrize(
    "name", ["[Content_Types].xml", "xl/styles.xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"]
)
def test_a_doctype_is_refused_in_every_parsed_part(name: str, no_openpyxl: None) -> None:
    original = part(BASE, name)
    declaration = '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
    if original.startswith("<?xml"):
        head, _, rest = original.partition("?>")
        hostile = head + "?>" + declaration + rest
    else:
        hostile = declaration + original
    error = refused(rewrite_xlsx(BASE, {name: hostile}))
    assert error.status == 415 and error.message_fa == DAMAGED_MESSAGE


def test_tree_parts_share_one_budget(monkeypatch: pytest.MonkeyPatch, no_openpyxl: None) -> None:
    monkeypatch.setattr(reader, "MAX_TREE_ELEMENTS", 400)
    styles = part(BASE, "xl/styles.xml")
    start, end = styles.index("<cellXfs"), styles.index("</cellXfs>") + len("</cellXfs>")
    bloated = (
        styles[:start] + '<cellXfs count="500">' + '<xf numFmtId="0"/>' * 500 + "</cellXfs>" + styles[end:]
    )
    assert refused(rewrite_xlsx(BASE, {"xl/styles.xml": bloated})).status == 413


def test_the_default_tree_budget_admits_ordinary_files() -> None:
    assert inspect(BASE, "xlsx").sheets[0].rows == 1


def test_shared_strings_are_capped(monkeypatch: pytest.MonkeyPatch, no_openpyxl: None) -> None:
    rows = '<row r="1"><c r="A1" t="s"><v>0</v></c></row><row r="2"><c r="A2"><v>1</v></c></row>'
    monkeypatch.setattr(reader, "MAX_SHARED_STRINGS", 10)
    assert refused(with_shared_strings("<si><t>s</t></si>" * 11, rows)).status == 413
    monkeypatch.setattr(reader, "MAX_SHARED_STRINGS", 1000)
    monkeypatch.setattr(reader, "MAX_RETAINED_ELEMENTS", 20)
    assert refused(with_shared_strings("<si><t>s</t></si>" + "<junk/>" * 30, rows)).status == 413


def test_nesting_depth_is_capped(no_openpyxl: None) -> None:
    deep = "<x>" * 70 + "</x>" * 70
    assert refused(with_rows(f'<row r="1"><c><v>1</v></c></row>{deep}')).status == 413


def test_parts_openpyxl_never_opens_are_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reader, "MAX_TREE_ELEMENTS", 400)
    big_cache = "<pivotCacheRecords>" + '<r><n v="1"/></r>' * 2000 + "</pivotCacheRecords>"
    data = rewrite_xlsx(
        BASE,
        {
            "xl/pivotCache/pivotCacheRecords1.xml": big_cache,  # not referenced by any sheet: never parsed
            "xl/worksheets/sheet99.xml": "<worksheet><sheetData>"
            + "<x/>" * 2000
            + "</sheetData></worksheet>",
        },
    )
    assert inspect(data, "xlsx").sheets[0].rows == 1


def test_sheet_roles_come_from_the_workbook_not_from_names(no_openpyxl: None) -> None:
    """A worksheet stored under an unusual name is still checked as a worksheet."""
    giant = '<row r="1">' + "<c><v>1</v></c>" * 120_000 + "</row>"
    moved = with_rows(giant)
    sheet = part(moved, "xl/worksheets/sheet1.xml")
    parts = {
        "xl/data/table.xml": sheet,
        "xl/worksheets/sheet1.xml": part(
            BASE, "xl/worksheets/sheet1.xml"
        ),  # harmless decoy at the usual name
        "xl/_rels/workbook.xml.rels": part(moved, "xl/_rels/workbook.xml.rels").replace(
            "worksheets/sheet1.xml", "data/table.xml"
        ),
    }
    assert "data/table.xml" in parts["xl/_rels/workbook.xml.rels"]
    assert refused(rewrite_xlsx(moved, parts)).status == 413


def test_with_chart_sheets_every_other_part_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["n"])
    worksheet.append([1])
    workbook.create_chartsheet("Chart")
    buffer = io.BytesIO()
    workbook.save(buffer)
    data = rewrite_xlsx(
        buffer.getvalue(),
        {
            # Real chart sheets always have a relationships part; openpyxl cannot read one without it.
            "xl/chartsheets/_rels/sheet1.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
            ),
            "xl/extra/notes.xml": "<notes>" + "<n/>" * 2000 + "</notes>",
        },
    )
    assert inspect(data, "xlsx").sheets[0].rows == 1  # within the default budget
    monkeypatch.setattr(reader, "MAX_TREE_ELEMENTS", 400)
    assert refused(data).status == 413  # the extra part counts once a chart sheet is present
