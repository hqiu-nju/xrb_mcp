"""Portable fixtures are entirely synthetic and contain no scientific evidence."""

import json
import os
import shutil
import sqlite3
import struct
import sys
import uuid
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.database.portable_schema import DATABASE_FILENAME, MANIFEST_FILENAME, SCHEMA
from xrb_mcp.ingestion.embeddings import get_embedding_backend
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.portable import PortableReader
from xrb_mcp.server.config import get_settings


def _id(number):
    return str(uuid.UUID(int=number))


SOURCE_PLUS = _id(1)
SOURCE_MINUS = _id(2)
CATALOGUE_ONLY = "synthetic-catalogue-only"
PAPER_IDS = [_id(number) for number in (11, 12, 13)]
CHUNK_IDS = [_id(number) for number in (21, 22, 23)]


@pytest.fixture
def portable_dataset(tmp_path):
    """Small overlapping records expose accidental broadening of any filter."""
    folder = tmp_path / "dataset"
    folder.mkdir()
    sources = [
        {
            "id": SOURCE_PLUS,
            "canonical_name": "SYNTHETIC J1200+1000",
            "source_class": "LMXB",
            "aliases": [{"alias": "synthetic-plus", "type": "test", "authority": "fixture"}],
        },
        {
            "id": SOURCE_MINUS,
            "canonical_name": "SYNTHETIC J1200-1000",
            "source_class": "HMXB",
            "aliases": [{"alias": "synthetic-minus", "type": "test", "authority": "fixture"}],
        },
    ]
    for source in sources:
        source.update(
            compact_object_type=None,
            ra_deg=None,
            dec_deg=None,
            authority="Synthetic test fixture; not scientific evidence",
            notes="Synthetic test fixture; not scientific evidence",
        )
    manifest = {
        "format_version": 1,
        "database": {"filename": DATABASE_FILENAME},
        "counts": {"sources": 2, "papers": 3, "chunks": 3, "catalogue_sources": 1},
        "flags": {"include_embeddings": True, "include_originals": False},
        "external_links": {
            "papers": "https://example.invalid/synthetic-papers",
            "catalogues": "https://example.invalid/synthetic-catalogues",
        },
    }
    (folder / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    with sqlite3.connect(folder / DATABASE_FILENAME) as conn:
        conn.executescript(SCHEMA)
        for key, value in (("format_version", 1), ("manifest", manifest)):
            conn.execute("INSERT INTO snapshot_metadata VALUES (?, ?)", (key, json.dumps(value)))
        for source in sources:
            conn.execute(
                "INSERT INTO sources VALUES (?, ?, ?)",
                (source["id"], normalize_alias(source["canonical_name"]), json.dumps(source)),
            )
            for alias in [source["canonical_name"], *[a["alias"] for a in source["aliases"]]]:
                conn.execute(
                    "INSERT INTO source_aliases VALUES (?, ?)",
                    (normalize_alias(alias), source["id"]),
                )
        for index, (source_id, year, collection, wavelength, instrument, topic) in enumerate(
            [
                (SOURCE_PLUS, 2024, "selected", "radio", "synthetic-array", "jets"),
                (SOURCE_MINUS, 2023, "selected", "infrared", "synthetic-camera", "timing"),
                (SOURCE_PLUS, 2000, "legacy", "X-ray", "synthetic-camera", "timing"),
            ]
        ):
            paper_id, chunk_id = PAPER_IDS[index], CHUNK_IDS[index]
            paper = {
                "id": paper_id,
                "title": f"Synthetic portable fixture {index + 1}",
                "authors": ["Synthetic Fixture"],
                "publication_year": year,
                "journal": "Synthetic test fixture",
                "doi": f"10.0000/synthetic.{index + 1}",
                "arxiv_id": None,
                "ads_bibcode": None,
                "source_url": None,
                "citation_url": f"https://doi.org/10.0000/synthetic.{index + 1}",
                "abstract": "Synthetic test fixture; not scientific evidence",
                "metadata_method": "synthetic_fixture",
                "sources": [
                    {"id": source_id, "canonical_name": sources[index % 2]["canonical_name"]}
                ],
                "sections": [
                    {
                        "chunk_id": chunk_id,
                        "section": "Synthetic results",
                        "page_start": index + 2,
                        "page_end": index + 3,
                        "provenance_id": _id(index + 31),
                    }
                ],
                "wavelengths": [wavelength],
                "instruments": [instrument],
                "page_numbering": "pdf_1_based",
            }
            text = f"Synthetic fixture {index + 1}: radio passage. Not scientific evidence."
            evidence = {
                "chunk_id": chunk_id,
                "section": "Synthetic results",
                "page_start": index + 2,
                "page_end": index + 3,
                "page_numbering": "pdf_1_based",
                "source_ids": [source_id],
                "wavelengths": [wavelength],
                "instruments": [instrument],
                "topics": [topic],
                "provenance": {
                    "id": _id(index + 31),
                    "extraction_method": "synthetic_fixture",
                    "confidence": 1.0,
                    "verified_by_user": False,
                    "details": {"notice": "Synthetic test fixture; not scientific evidence"},
                },
                "evidence_kind": "extracted_passage",
            }
            vector = ([10.0, 1.0, 0.0], [1.0, 10.0, 0.0], [1.0, 1.0])[index]
            conn.execute("INSERT INTO papers VALUES (?, ?)", (paper_id, json.dumps(paper)))
            conn.execute("INSERT INTO paper_sources VALUES (?, ?)", (paper_id, source_id))
            conn.execute("INSERT INTO collection_papers VALUES (?, ?)", (collection, paper_id))
            conn.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    chunk_id,
                    paper_id,
                    0,
                    text,
                    json.dumps(evidence),
                    struct.pack(f"<{len(vector)}f", *vector),
                    "synthetic-embedding",
                    "fixture-v1",
                    len(vector),
                ),
            )
        catalogue = {
            "id": CATALOGUE_ONLY,
            "source_id": CATALOGUE_ONLY,
            "canonical_name": "SYNTHETIC catalogue only",
            "source_classes": ["LMXB"],
            "aliases": ["synthetic catalogue alias"],
            "authority": "Synthetic test catalogue; not scientific evidence",
        }
        conn.execute(
            "INSERT INTO catalogue_sources VALUES (?, ?)",
            (CATALOGUE_ONLY, json.dumps(catalogue)),
        )
        conn.execute(
            "INSERT INTO catalogue_aliases VALUES (?, ?)",
            (normalize_alias("synthetic catalogue alias"), CATALOGUE_ONLY),
        )
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    return folder


def test_portable_reader_resolves_aliases_and_preserves_coordinate_signs(portable_dataset):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        assert reader.source_object(" SYNTHETIC-PLUS ")["id"] == SOURCE_PLUS
        assert reader.source_object("synthetic j1200+1000")["id"] == SOURCE_PLUS
        assert reader.source_object("SYNTHETIC J1200−1000")["id"] == SOURCE_MINUS
        assert reader.source_object(SOURCE_MINUS)["canonical_name"] == "SYNTHETIC J1200-1000"


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, CHUNK_IDS),
        ({"source": "synthetic-plus"}, [CHUNK_IDS[0], CHUNK_IDS[2]]),
        ({"source_class": "HMXB"}, [CHUNK_IDS[1]]),
        ({"wavelengths": ["radio"]}, [CHUNK_IDS[0]]),
        ({"instruments": ["synthetic-array"]}, [CHUNK_IDS[0]]),
        ({"topics": ["jets"]}, [CHUNK_IDS[0]]),
        ({"year_min": 2024, "year_max": 2024}, [CHUNK_IDS[0]]),
        ({"collection": "legacy"}, [CHUNK_IDS[2]]),
        ({"source": "synthetic-plus", "year_min": 2024, "collection": "selected"}, [CHUNK_IDS[0]]),
        ({"wavelengths": ["radio", "infrared"], "topics": ["timing"]}, [CHUNK_IDS[1]]),
        ({"wavelengths": ["radio"], "instruments": ["synthetic-camera"]}, []),
    ],
)
def test_portable_fts_respects_filters(portable_dataset, filters, expected):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        response = reader.search_literature("radio", LiteratureFilters(**filters))
    assert {result["chunk_id"] for result in response["results"]} == set(expected)
    assert response["synthesis_generated"] is False


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ('"radio passage"', CHUNK_IDS),
        ('"radio passage', CHUNK_IDS),
        ("radio OR unmatchedword", CHUNK_IDS),
        ("radio -passage", []),
        ("-radio", []),
        ("?!()", []),
        ("radio; DROP TABLE papers;", []),
    ],
)
def test_portable_queries_handle_phrases_exclusions_and_malformed_input(
    portable_dataset, query, expected
):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        response = reader.search_literature(query, LiteratureFilters())
        assert {result["chunk_id"] for result in response["results"]} == set(expected)
        assert reader.paper_object(PAPER_IDS[0])["id"] == PAPER_IDS[0]


def test_portable_search_and_paper_keep_citation_and_provenance(portable_dataset):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        response = reader.search_literature(
            "radio", LiteratureFilters(source="synthetic-plus", top_k=1)
        )
        result = response["results"][0]
        paper = reader.paper_object("https://doi.org/10.0000/synthetic.1")
        assert reader.paper_object("SYNTHETIC PORTABLE FIXTURE 1") == paper
        assert reader.paper_object(PAPER_IDS[0]) == paper
    assert result["paper"]["citation_url"] == "https://doi.org/10.0000/synthetic.1"
    assert result["provenance"]["id"] == _id(31)
    assert result["provenance"]["details"] == {
        "notice": "Synthetic test fixture; not scientific evidence"
    }
    assert result["page_start"] == 2
    assert result["page_end"] == 3
    assert result["page_numbering"] == "pdf_1_based"
    assert result["retrieval_channels"] == ["lexical"]
    assert paper["sections"][0]["provenance_id"] == result["provenance"]["id"]
    assert "pdf_path" not in json.dumps(response)


def test_unknown_or_catalogue_only_source_cannot_broaden_search(portable_dataset):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        with pytest.raises(ValueError, match="[Ss]ource"):
            reader.search_literature(
                "radio", LiteratureFilters(source="unregistered synthetic source")
            )
        catalogue = reader.source_object("synthetic catalogue alias")
        assert catalogue["canonical_name"] == "SYNTHETIC catalogue only"
        response = reader.search_literature(
            "radio", LiteratureFilters(source="synthetic catalogue alias")
        )
    assert response["results"] == []


class SyntheticEmbeddings:
    model = "synthetic-embedding"
    version = "fixture-v1"
    dimension = 3

    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_portable_cosine_search_uses_only_compatible_embeddings(portable_dataset):
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        response = reader.search_literature(
            "unmatchedword", LiteratureFilters(), SyntheticEmbeddings()
        )
    assert [result["chunk_id"] for result in response["results"]] == CHUNK_IDS[:2]
    assert all(result["retrieval_channels"] == ["semantic"] for result in response["results"])
    assert response["warnings"]
    assert response["mode"] == "hybrid"


def test_mismatched_embedding_version_keeps_lexical_search(portable_dataset):
    backend = SyntheticEmbeddings()
    backend.version = "different-fixture-version"
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        response = reader.search_literature("radio", LiteratureFilters(), backend)
    assert {result["chunk_id"] for result in response["results"]} == set(CHUNK_IDS)
    assert all(result["retrieval_channels"] == ["lexical"] for result in response["results"])
    assert response["warnings"]


def test_portable_dataset_remains_usable_after_relocation_without_originals(
    portable_dataset, tmp_path
):
    destination = tmp_path / "copied-repository" / "data" / "dataset"
    shutil.copytree(portable_dataset, destination)
    portable_dataset.rename(portable_dataset.with_name("original-no-longer-present"))
    assert sorted(path.name for path in destination.iterdir()) == [
        MANIFEST_FILENAME,
        DATABASE_FILENAME,
    ]
    with PortableReader(destination / DATABASE_FILENAME) as reader:
        assert reader.paper_object(PAPER_IDS[0])["id"] == PAPER_IDS[0]
        assert reader.search_literature("radio", LiteratureFilters())["results"]
        assert reader.dataset_info()["format_version"] == 1


def test_portable_database_is_opened_read_only(portable_dataset, monkeypatch):
    original_connect = sqlite3.connect
    connections = []

    def tracked_connect(database, *args, **kwargs):
        assert "mode=ro" in str(database)
        assert kwargs.get("uri") is True
        conn = original_connect(database, *args, **kwargs)
        connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    with PortableReader(portable_dataset / DATABASE_FILENAME) as reader:
        reader.source_object(SOURCE_PLUS)
        assert connections
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connections[-1].execute("UPDATE sources SET data_json = '{}'")


def test_missing_portable_database_fails_without_creating_a_file(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises((ValueError, FileNotFoundError)):
        with PortableReader(path):
            pass
    assert not path.exists()


def test_incompatible_portable_schema_is_rejected(portable_dataset):
    database = portable_dataset / DATABASE_FILENAME
    with sqlite3.connect(database) as conn:
        conn.execute("UPDATE snapshot_metadata SET value_json = '999' WHERE key = 'format_version'")
    with pytest.raises(ValueError, match="version|schema|format"):
        with PortableReader(database):
            pass


def test_version_marker_alone_does_not_establish_a_complete_schema(tmp_path):
    path = tmp_path / "incomplete.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE snapshot_metadata (key TEXT PRIMARY KEY, value_json TEXT)")
        conn.execute("INSERT INTO snapshot_metadata VALUES ('format_version', '1')")
    with pytest.raises(ValueError, match="invalid|schema") as error:
        with PortableReader(path):
            pass
    assert str(tmp_path) not in str(error.value)


@pytest.fixture
def portable_mode(portable_dataset, monkeypatch):
    monkeypatch.setenv("XRB_DATABASE_MODE", "portable")
    monkeypatch.setenv("XRB_DATASET_DIR", str(portable_dataset))
    monkeypatch.setenv("XRB_EMBEDDING_BACKEND", "none")
    get_settings.cache_clear()
    get_embedding_backend.cache_clear()
    yield portable_dataset
    get_settings.cache_clear()
    get_embedding_backend.cache_clear()


async def test_portable_tools_and_resources_never_open_postgresql(portable_mode, monkeypatch):
    import xrb_mcp.database.connection as connection
    from xrb_mcp.server.main import create_server
    from xrb_mcp.server.tools.literature import get_paper, search_literature
    from xrb_mcp.server.tools.sources import get_source

    def forbidden_postgresql(*args, **kwargs):
        pytest.fail("Portable mode attempted to open a PostgreSQL connection")

    monkeypatch.setattr(connection, "create_engine", forbidden_postgresql)
    assert get_source("synthetic-plus")["id"] == SOURCE_PLUS
    assert get_paper(PAPER_IDS[0])["id"] == PAPER_IDS[0]
    assert search_literature("radio", source="synthetic-plus")["results"]
    server = create_server()
    assert {tool.name for tool in await server.list_tools()} == {
        "get_source",
        "get_paper",
        "search_literature",
    }
    assert len(await server.list_resource_templates()) == 3
    for uri, expected in [
        (f"xrb://sources/{SOURCE_PLUS}", SOURCE_PLUS),
        (f"xrb://papers/{PAPER_IDS[0]}", PAPER_IDS[0]),
    ]:
        resource = await server.read_resource(uri)
        assert json.loads(next(iter(resource)).content)["id"] == expected
    ontology = await server.read_resource("xrb://ontology/wavelengths")
    assert "radio" in json.loads(next(iter(ontology)).content)["terms"]
    dataset_resource = await server.read_resource("xrb://dataset")
    info = json.loads(next(iter(dataset_resource)).content)
    assert info["database_mode"] == "portable"
    assert info["read_only"] is True
    assert info["counts"]["papers"] == 3
    assert info["external_links"]["papers"] == "https://example.invalid/synthetic-papers"
    assert info["catalogues"] == []
    assert info["catalogue_registry_review"] == []
    assert str(portable_mode) not in json.dumps(info)


async def test_real_stdio_client_uses_portable_dataset_without_postgresql(portable_mode):
    """The production entry point must work for another user with only a copied snapshot."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "xrb_mcp.server.main"],
        cwd=str(Path(__file__).resolve().parents[2]),
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src"),
            "XRB_DATABASE_MODE": "portable",
            "XRB_DATASET_DIR": str(portable_mode),
            "XRB_EMBEDDING_BACKEND": "none",
            "XRB_DATABASE_URL": "postgresql+psycopg://unused@127.0.0.1:1/unavailable",
            "XRB_READ_DATABASE_URL": "postgresql+psycopg://unused@127.0.0.1:1/unavailable",
        },
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        assert {tool.name for tool in (await client.list_tools()).tools} == {
            "get_source",
            "get_paper",
            "search_literature",
        }
        for name, arguments in [
            ("get_source", {"source": "synthetic-plus"}),
            ("get_paper", {"identifier": PAPER_IDS[0]}),
            ("search_literature", {"query": "radio", "source": "synthetic-plus"}),
        ]:
            response = await client.call_tool(name, arguments)
            assert not response.isError, response
            assert response.content
        for uri in [
            f"xrb://sources/{SOURCE_PLUS}",
            f"xrb://papers/{PAPER_IDS[0]}",
            "xrb://ontology/wavelengths",
            "xrb://dataset",
        ]:
            assert (await client.read_resource(uri)).contents
        error = await client.call_tool(
            "search_literature", {"query": "radio", "source": "unknown synthetic source"}
        )
        assert error.isError
