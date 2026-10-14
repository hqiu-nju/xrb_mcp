"""End-to-end SQLite snapshots built only from explicitly synthetic records."""

import hashlib
import json
import sqlite3
import struct
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.database.models import (
    Collection,
    CollectionPaper,
    Paper,
    PaperChunk,
    PaperSource,
    Provenance,
    Source,
    SourceAlias,
)
from xrb_mcp.database.portable_schema import DATABASE_FILENAME, MANIFEST_FILENAME
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.portable import PortableReader
from xrb_mcp.scripts import dataset as dataset_tools
from xrb_mcp.scripts.export_dataset import _scrub, export_dataset
from xrb_mcp.scripts.source_catalogues import _write_database


class Rows(list):
    def all(self):
        return self


class SnapshotSession:
    """Only database IO is stubbed; actual ORM rows and export serialization run."""

    def __init__(self, rows, chunks):
        self.rows = rows
        self.chunks = chunks

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="synthetic-test-stub"))

    def scalars(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        return Rows(self.rows[entity])

    def get(self, entity, identifier):
        return next((row for row in self.rows[entity] if row.id == identifier), None)

    def execute(self, statement):
        assert [column["entity"] for column in statement.column_descriptions] == [
            PaperChunk,
            Provenance,
        ]
        return self.chunks


@pytest.fixture
def export_session(tmp_path):
    original = tmp_path / "data" / "papers" / "synthetic.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"SYNTHETIC test bytes. Not a paper or scientific evidence.")
    source = Source(
        id=uuid.UUID(int=101),
        canonical_name="SYNTHETIC J1200+1000",
        normalized_name=normalize_alias("SYNTHETIC J1200+1000"),
        source_class="LMXB",
        authority="Synthetic fixture; not scientific evidence",
        notes="Synthetic fixture; not scientific evidence",
    )
    paper = Paper(
        id=uuid.UUID(int=111),
        title="Synthetic export fixture; not scientific evidence",
        authors=["Synthetic Fixture"],
        publication_year=2024,
        journal="Synthetic fixture",
        doi="10.0000/synthetic.export",
        abstract="Synthetic fixture; not scientific evidence",
        pdf_path=str(original),
        content_hash=hashlib.sha256(original.read_bytes()).hexdigest(),
        metadata_method="synthetic_fixture",
    )
    chunk = PaperChunk(
        id=uuid.UUID(int=121),
        paper_id=paper.id,
        chunk_index=0,
        section="Synthetic section",
        subsection="Synthetic subsection",
        page_start=2,
        page_end=3,
        text="SYNTHETIC radio test passage. Not scientific evidence.",
        token_count=9,
        source_ids=[source.id],
        wavelengths=["radio"],
        instruments=["synthetic-instrument"],
        topics=["synthetic-topic"],
        embedding=[1.0, 2.0, 3.0],
        embedding_model="synthetic-embedding",
        embedding_version="synthetic-v1",
        embedding_dimension=3,
    )
    provenance = Provenance(
        id=uuid.UUID(int=131),
        paper_id=paper.id,
        chunk_id=chunk.id,
        page=2,
        section="Synthetic section",
        extraction_method="synthetic_fixture",
        confidence=1.0,
        verified_by_user=False,
        details={
            "notice": "Synthetic fixture; not scientific evidence",
            "path": str(original),
            "nested": {"database_url": "postgresql://secret", "token": "fixture-secret"},
        },
    )
    rows = {
        Source: [source],
        SourceAlias: [
            SourceAlias(
                id=uuid.UUID(int=141),
                source_id=source.id,
                alias="synthetic-plus",
                normalized_alias=normalize_alias("synthetic-plus"),
                alias_type="synthetic",
                authority="synthetic_fixture",
            )
        ],
        Paper: [paper],
        PaperSource: [PaperSource(paper_id=paper.id, source_id=source.id)],
        Collection: [Collection(name="synthetic", description="Synthetic fixture")],
        CollectionPaper: [CollectionPaper(collection="synthetic", paper_id=paper.id)],
    }
    return SnapshotSession(rows, [(chunk, provenance)])


def test_exported_index_is_searchable_without_originals_or_embeddings(export_session, tmp_path):
    output = tmp_path / "export"
    manifest = export_dataset(export_session, output, papers_url="https://example.invalid/papers")
    assert sorted(path.name for path in output.iterdir()) == [MANIFEST_FILENAME, DATABASE_FILENAME]
    assert manifest["flags"] == {"include_originals": False, "include_embeddings": False}
    assert manifest["counts"]["chunks"] == 1
    assert manifest["counts"]["embeddings"] == 0
    assert manifest["assets"][0]["available"] is False
    assert manifest["assets"][0]["archive_url"].startswith("https://example.invalid/papers/")
    with PortableReader(output / DATABASE_FILENAME) as reader:
        response = reader.search_literature("radio", LiteratureFilters(collection="synthetic"))
        evidence = response["results"][0]
        assert evidence["provenance"]["id"] == str(uuid.UUID(int=131))
        assert evidence["page_start"] == 2
        assert evidence["page_end"] == 3
        assert evidence["paper"]["archive_path"] == manifest["assets"][0]["path"]
        public_json = json.dumps(evidence)
        assert str(tmp_path) not in public_json
        assert "fixture-secret" not in public_json
        assert "postgresql://secret" not in public_json
    assert dataset_tools.validate_dataset(output)["valid"] is True


def test_export_with_originals_and_embeddings_is_complete(export_session, tmp_path):
    output = tmp_path / "export"
    manifest = export_dataset(
        export_session, output, include_embeddings=True, include_originals=True
    )
    assert manifest["counts"]["embeddings"] == 1
    asset = manifest["assets"][0]
    assert asset["available"] is True
    assert (output / asset["path"]).read_bytes().startswith(b"SYNTHETIC")
    with sqlite3.connect(output / DATABASE_FILENAME) as conn:
        blob, model, version, dimension = conn.execute(
            "SELECT embedding, embedding_model, embedding_version, embedding_dimension FROM chunks"
        ).fetchone()
    assert blob == struct.pack("<3f", 1.0, 2.0, 3.0)
    assert (model, version, dimension) == ("synthetic-embedding", "synthetic-v1", 3)
    assert dataset_tools.validate_dataset(output, verify_assets=True)["assets_checked"] == 1


def test_export_scrubs_machine_paths_embedded_in_citation_authority(export_session, tmp_path):
    source = export_session.rows[Source][0]
    source.authority = (
        "Synthetic identification; DOI 10.0000/synthetic.export; PDF page 1; identity only. "
        "/Users/synthetic/Documents/radio/4U1210 paper/literature/synthetic paper.pdf; "
        "flux units erg/s/cm^2; citation https://example.invalid/Users/public/paper.pdf"
    )
    output = tmp_path / "export"
    export_dataset(export_session, output)
    with PortableReader(output / DATABASE_FILENAME) as reader:
        authority = reader.source_object(source.canonical_name)["authority"]
    assert "10.0000/synthetic.export" in authority
    assert "PDF page 1; identity only. synthetic paper.pdf" in authority
    assert "erg/s/cm^2" in authority
    assert "https://example.invalid/Users/public/paper.pdf" in authority
    assert "/Users/synthetic" not in authority
    assert "/Documents/radio" not in authority


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        (
            "Citation (/home/user/papers/a paper.pdf). Flux erg/s/cm^2.",
            "Citation (a paper.pdf). Flux erg/s/cm^2.",
        ),
        (
            "Citation /Users/user/O'Brien papers/a paper.pdf. Flux erg/s/cm^2.",
            "Citation a paper.pdf. Flux erg/s/cm^2.",
        ),
        (
            r"Citation C:\Users\user\My Papers\a paper.pdf; DOI 10.0000/synthetic",
            "Citation a paper.pdf; DOI 10.0000/synthetic",
        ),
        (
            "Citation file:///Users/user/My Papers/a paper.pdf; retained.",
            "Citation a paper.pdf; retained.",
        ),
        (
            "https://example.invalid/Users/public/paper.pdf",
            "https://example.invalid/Users/public/paper.pdf",
        ),
        (
            "Scientific units /s and erg/s/cm^2; catalogue label /data-point.",
            "Scientific units /s and erg/s/cm^2; catalogue label /data-point.",
        ),
    ],
)
def test_embedded_path_scrubbing_preserves_scientific_prose_and_urls(original, expected):
    assert _scrub(original, "authority") == expected


def test_export_failure_preserves_previously_published_dataset(export_session, tmp_path):
    output = tmp_path / "export"
    export_dataset(export_session, output)
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    export_session.chunks = [(export_session.chunks[0][0], None)]
    with pytest.raises(ValueError, match="provenance"):
        export_dataset(export_session, output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == previous


@pytest.mark.parametrize(("field", "value"), [("page", 99), ("section", "Wrong synthetic section")])
def test_inconsistent_passage_provenance_cannot_replace_published_dataset(
    export_session, tmp_path, field, value
):
    output = tmp_path / "export"
    export_dataset(export_session, output)
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    setattr(export_session.chunks[0][1], field, value)
    with pytest.raises(ValueError, match="provenance"):
        export_dataset(export_session, output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == previous


def test_export_rejects_originals_that_no_longer_match_provenance(export_session, tmp_path):
    paper = export_session.rows[Paper][0]
    with open(paper.pdf_path, "wb") as stream:
        stream.write(b"CHANGED synthetic fixture bytes")
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="checksum"):
        export_dataset(export_session, output, include_originals=True)
    assert not output.exists()


def test_index_export_allows_absent_originals(export_session, tmp_path):
    Path(export_session.rows[Paper][0].pdf_path).unlink()
    output = tmp_path / "export"
    manifest = export_dataset(export_session, output)
    assert manifest["assets"][0]["available"] is False
    with PortableReader(output / DATABASE_FILENAME) as reader:
        assert reader.search_literature("radio", LiteratureFilters())["results"]


def test_missing_original_cannot_replace_existing_complete_dataset(export_session, tmp_path):
    output = tmp_path / "export"
    export_dataset(export_session, output, include_originals=True)
    previous = {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    }
    Path(export_session.rows[Paper][0].pdf_path).unlink()
    with pytest.raises(ValueError, match="unavailable"):
        export_dataset(export_session, output, include_originals=True)
    assert {
        str(path.relative_to(output)): path.read_bytes()
        for path in output.rglob("*")
        if path.is_file()
    } == previous


def test_zero_norm_embedding_cannot_be_exported(export_session, tmp_path):
    export_session.chunks[0][0].embedding = [0.0, 0.0, 0.0]
    output = tmp_path / "export"
    with pytest.raises(ValueError, match="embedding"):
        export_dataset(export_session, output, include_embeddings=True)
    assert not output.exists()


def _synthetic_catalogue(tmp_path, alias_groups):
    catalogue_path = tmp_path / "synthetic-sources.db"
    catalogue = {
        "catalogue": "synthetic.csv",
        "origin": str(tmp_path / "missing-original" / "synthetic.csv"),
        "format": "csv",
        "sha256": "a" * 64,
        "source_rows": 2,
        "notice": "Synthetic fixture; not scientific evidence",
    }
    sources, rows = [], []
    for index, aliases in enumerate(alias_groups, 1):
        sources.append(
            {
                "source_id": f"synthetic-catalogue-{index}",
                "canonical_name": aliases[0],
                "ra_deg": None,
                "dec_deg": None,
                "source_classes": ["LMXB"],
                "coordinate_origin": {},
                "aliases": aliases,
                "match_methods": ["synthetic_fixture"],
                "member_keys": [[catalogue["catalogue"], index]],
            }
        )
        rows.append(
            {
                "catalogue": catalogue["catalogue"],
                "row_index": index,
                "raw": {"name": aliases[0], "missing_measurement": None, "notice": "Synthetic"},
            }
        )
    _write_database(
        catalogue_path,
        [catalogue],
        rows,
        {catalogue["catalogue"]: []},
        {"sources": sources, "matches": [], "review": []},
        {"notice": "Synthetic fixture; not scientific evidence"},
    )
    return catalogue_path


def test_catalogue_export_keeps_original_row_provenance_and_identity_links(
    export_session, tmp_path
):
    catalogue_path = _synthetic_catalogue(tmp_path, [["synthetic-plus"], ["synthetic-only"]])
    output = tmp_path / "export"
    manifest = export_dataset(
        export_session,
        output,
        catalogue_database=catalogue_path,
        catalogues_url="https://example.invalid/catalogues",
    )
    assert manifest["counts"]["catalogue_links"] == 1
    assert manifest["counts"]["catalogue_rows"] == 2
    with PortableReader(output / DATABASE_FILENAME) as reader:
        source = reader.source_object("synthetic-plus")
        dataset_info = reader.dataset_info(include_catalogues=True)
        assert dataset_info["collections"] == [
            {"name": "synthetic", "description": "Synthetic fixture"}
        ]
        assert dataset_info["catalogues"][0]["archive_path"] == "catalogues/synthetic.csv"
        assert dataset_info["catalogue_registry_review"] == []
        member = source["catalogue_matches"][0]["member_rows"][0]
        assert member["row_index"] == 1
        assert member["raw"]["missing_measurement"] is None
        assert member["catalogue_input"]["archive_path"] == "catalogues/synthetic.csv"
        assert member["catalogue_input"]["archive_url"] == (
            "https://example.invalid/catalogues/synthetic.csv"
        )
        assert str(tmp_path) not in json.dumps(source)
        assert reader.source_object("synthetic-only")["identity_scope"] == "catalogue"
        assert (
            reader.search_literature("radio", LiteratureFilters(source="synthetic-only"))["results"]
            == []
        )


def test_catalogue_aliases_cannot_link_one_registered_source_to_two_identities(
    export_session, tmp_path
):
    catalogue_path = _synthetic_catalogue(tmp_path, [["synthetic-plus"], ["SYNTHETIC J1200+1000"]])
    output = tmp_path / "export"
    manifest = export_dataset(export_session, output, catalogue_database=catalogue_path)
    assert manifest["counts"]["catalogue_links"] == 0
    with PortableReader(output / DATABASE_FILENAME) as reader:
        assert reader.source_object("synthetic-plus")["catalogue_matches"] == []
    with sqlite3.connect(output / DATABASE_FILENAME) as conn:
        review = json.loads(
            conn.execute(
                "SELECT value_json FROM snapshot_metadata WHERE key = 'catalogue_registry_review'"
            ).fetchone()[0]
        )
    assert len(review) == 2
    assert all(len(item["conflicting_catalogue_source_ids"]) == 2 for item in review)


@pytest.fixture
def remote_dataset(export_session, tmp_path):
    output = tmp_path / "remote"
    manifest = export_dataset(export_session, output)
    return manifest, (output / DATABASE_FILENAME).read_bytes()


def _mock_download(monkeypatch, manifest, database_bytes):
    requests = []
    original_client = httpx.Client

    def respond(request):
        requests.append(str(request.url))
        if request.url.path.endswith("/" + MANIFEST_FILENAME):
            return httpx.Response(200, json=manifest)
        if request.url.path.endswith("/" + DATABASE_FILENAME):
            return httpx.Response(200, content=database_bytes)
        pytest.fail(f"Unexpected download of an original or another resource: {request.url}")

    monkeypatch.setattr(
        dataset_tools.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    return requests


def test_downloader_transfers_only_index_and_manifest(remote_dataset, monkeypatch, tmp_path):
    manifest, database_bytes = remote_dataset
    requests = _mock_download(monkeypatch, manifest, database_bytes)
    output = tmp_path / "downloaded"
    result = dataset_tools.download_dataset("https://example.invalid/share/dataset.json", output)
    assert result["valid"] is True
    assert requests == [
        "https://example.invalid/share/dataset.json",
        "https://example.invalid/share/xrb.sqlite3",
    ]
    assert sorted(path.name for path in output.iterdir()) == [MANIFEST_FILENAME, DATABASE_FILENAME]
    with PortableReader(output / DATABASE_FILENAME) as reader:
        assert reader.search_literature("radio", LiteratureFilters())["results"]


@pytest.mark.parametrize("tamper", ["checksum", "size", "schema"])
def test_failed_download_never_publishes_an_invalid_snapshot(
    remote_dataset, monkeypatch, tmp_path, tamper
):
    manifest, database_bytes = remote_dataset
    if tamper == "checksum":
        manifest["database"]["sha256"] = "0" * 64
    elif tamper == "size":
        manifest["database"]["size_bytes"] = 1
    else:
        manifest["format_version"] = 999
    _mock_download(monkeypatch, manifest, database_bytes)
    output = tmp_path / "downloaded"
    with pytest.raises(ValueError):
        dataset_tools.download_dataset("https://example.invalid/share/dataset.json", output)
    assert not output.exists()


def test_downloader_preserves_existing_destination(remote_dataset, monkeypatch, tmp_path):
    manifest, database_bytes = remote_dataset
    requests = _mock_download(monkeypatch, manifest, database_bytes)
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("Existing data must remain intact")
    with pytest.raises(ValueError, match="not empty"):
        dataset_tools.download_dataset("https://example.invalid/share/dataset.json", output)
    assert marker.read_text() == "Existing data must remain intact"
    assert requests == []


def test_downloader_can_publish_into_an_existing_empty_directory(
    remote_dataset, monkeypatch, tmp_path
):
    manifest, database_bytes = remote_dataset
    requests = _mock_download(monkeypatch, manifest, database_bytes)
    output = tmp_path / "existing-empty"
    output.mkdir()
    result = dataset_tools.download_dataset("https://example.invalid/share/dataset.json", output)
    assert result["valid"] is True
    assert len(requests) == 2
    assert sorted(path.name for path in output.iterdir()) == [MANIFEST_FILENAME, DATABASE_FILENAME]
    assert (output / DATABASE_FILENAME).read_bytes() == database_bytes
