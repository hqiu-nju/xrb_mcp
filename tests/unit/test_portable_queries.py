"""Natural query syntax is accepted safely without exposing raw FTS5 grammar."""

import json
import sqlite3

import pytest

from xrb_mcp.database.portable_schema import SCHEMA
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.portable import PortableReader


@pytest.fixture
def query_dataset(tmp_path):
    path = tmp_path / "queries.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO snapshot_metadata VALUES ('format_version', '1')")
        connection.execute(
            "INSERT INTO papers VALUES (?, ?)",
            ("synthetic", json.dumps({"id": "synthetic", "title": "Synthetic query fixture"})),
        )
        for index, text in enumerate(
            ("radio jet compact", "radio burst compact", "x ray wind", "jet radio separated")
        ):
            data = {"source_ids": [], "page_start": 1, "page_end": 1, "provenance": {}}
            connection.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(index), "synthetic", index, text, json.dumps(data), None, None, None, None),
            )
        connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    return path


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("radio?", {"0", "1", "3"}),
        ('"radio jet"', {"0"}),
        ("radio OR x-ray", {"0", "1", "2", "3"}),
        ("radio -burst", {"0", "3"}),
        ('radio -"burst compact"', {"0", "3"}),
        ('"radio jet', {"0"}),
        ("radio OR OR", {"0", "1", "3"}),
        ("-radio", set()),
        ("*{}^:", set()),
    ],
)
def test_portable_natural_query_syntax(query_dataset, query, expected):
    with PortableReader(query_dataset) as reader:
        result = reader.search_literature(query, LiteratureFilters())
    assert {chunk["chunk_id"] for chunk in result["results"]} == expected
    assert result["retrieval_backend"] == "sqlite_fts5"


@pytest.mark.parametrize(
    "query",
    [
        'radio "); DROP TABLE chunks;--',
        "text:radio",
        "NEAR(radio, 10)",
        "radio OR (",
        '"',
        "\x00\n\t{}",
    ],
)
def test_malformed_or_raw_fts_input_does_not_execute_syntax(query_dataset, query):
    with PortableReader(query_dataset) as reader:
        reader.search_literature(query, LiteratureFilters())
        assert reader.paper_object("synthetic")["id"] == "synthetic"
        assert len(reader.search_literature("radio", LiteratureFilters())["results"]) == 3
    with sqlite3.connect(query_dataset) as connection:
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == 4
