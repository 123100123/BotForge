"""Builders for spreadsheet test files: real xlsx files written by openpyxl, and hand-assembled zips
for the malformed and malicious cases openpyxl would never write."""

import io
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

import openpyxl

Rows = Sequence[Sequence[Any]]


def make_xlsx(sheets: Mapping[str, Rows]) -> bytes:
    """An xlsx file with one worksheet per entry, rows appended in order."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def zip_bytes(parts: Mapping[str, bytes | str], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, content in parts.items():
            archive.writestr(name, content.encode() if isinstance(content, str) else content)
    return buffer.getvalue()


def rewrite_xlsx(data: bytes, parts: Mapping[str, bytes | str]) -> bytes:
    """``data`` with the given parts replaced or added (names exactly as in the zip)."""
    merged: dict[str, bytes | str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            merged[info.filename] = archive.read(info.filename)
    merged.update(parts)
    return zip_bytes(merged)


def sheet_xml(data: bytes, index: int = 1) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(f"xl/worksheets/sheet{index}.xml").decode()


def csv_bytes(lines: Sequence[str], *, encoding: str = "utf-8") -> bytes:
    return ("\n".join(lines) + "\n").encode(encoding)
