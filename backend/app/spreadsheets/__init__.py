"""Spreadsheet Intelligence, ingestion half (roadmap: Business OS, Spreadsheet Intelligence).

* ``storage``: ``FileStorage`` and ``LocalFileStorage`` (``UPLOAD_DIR``); keys are generated server-side.
* ``reader``: type sniffing from the bytes, zip/macro guards, bounded row iteration (openpyxl read-only,
  stdlib csv) and value normalisation.
* ``inspect``: the deterministic ``WorkbookInspection`` and the layout signature.
* ``service``: ``ingest`` (the single entry point for web uploads and, later, Telegram documents),
  listing and reading uploads back, ``load_rows`` for the analysis layer.
* ``errors``: ``SpreadsheetError`` and its subclasses, each with a code, a Persian message and a status.

The HTTP surface is ``app.api.uploads``.
"""
