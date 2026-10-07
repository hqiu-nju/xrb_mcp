import pytest

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.ingestion.catalogues import read_catalogue
from xrb_mcp.ingestion.chunking import chunk_blocks
from xrb_mcp.ingestion.embeddings import checked_embeddings
from xrb_mcp.ingestion.metadata import PaperMetadata
from xrb_mcp.ingestion.pdf_parser import TextBlock, parse_pdf
from xrb_mcp.ingestion.tagging import tag_text
from xrb_mcp.retrieval.filters import LiteratureFilters
from xrb_mcp.retrieval.ranking import reciprocal_rank_fusion


def test_normalization_preserves_coordinate_signs():
    assert normalize_alias(" MAXI J1820+070 ") == normalize_alias("maxi j1820+070")
    assert normalize_alias("GX 339−4") == "gx339-4"
    assert normalize_alias("J1820+070") != normalize_alias("J1820-070")
    with pytest.raises(ValueError):
        normalize_alias(" ")


def test_pdf_page_section_provenance(pdf_factory):
    parsed = parse_pdf(pdf_factory())
    chunks = chunk_blocks(parsed.blocks)
    assert len(chunks) == 2
    assert chunks[1].section == "2 Results"
    assert chunks[1].page_start == chunks[1].page_end == 2
    assert "MeerKAT" in chunks[1].text


def test_chunks_preserve_all_words_and_never_cross_sections():
    blocks = [
        TextBlock("one two three", 1, "Intro"),
        TextBlock("four five six seven eight nine ten", 2, "Intro"),
        TextBlock("eleven twelve", 3, "Results"),
    ]
    chunks = chunk_blocks(blocks, max_words=4)
    assert " ".join(c.text for c in chunks).split() == " ".join(b.text for b in blocks).split()
    assert all(len(c.text.split()) <= 4 for c in chunks)
    assert chunks[-1].section == "Results"
    assert chunks[-1].page_start == 3


def test_identifier_normalization_and_invalid_metadata():
    metadata = PaperMetadata(doi="https://doi.org/10.1234/TEST", arxiv_id="arXiv:1803.12345v2")
    assert metadata.doi == "10.1234/test"
    assert metadata.arxiv_id == "1803.12345"
    with pytest.raises(ValueError):
        PaperMetadata(doi="invented", unsupported=True)


def test_filters_validate_bounds_and_fusion_rewards_agreement():
    with pytest.raises(ValueError):
        LiteratureFilters(year_min=2020, year_max=2018)
    with pytest.raises(ValueError):
        LiteratureFilters(top_k=10000)
    scores = reciprocal_rank_fusion(["a", "b"], ["b", "c"])
    assert scores["b"] > scores["a"] > scores["c"]


def test_tags_are_whole_terms():
    assert "radio" in tag_text("MeerKAT detected an ejection")["wavelengths"]
    assert "VLA" not in tag_text("VLASS")["instruments"]


def test_invalid_embedding_batch_is_rejected(backend):
    backend.embed = lambda texts: [[float("nan"), 0, 1] for _ in texts]
    with pytest.raises(ValueError, match="finite"):
        checked_embeddings(backend, ["radio"])


def test_scanned_pdf_is_rejected(pdf_factory):
    with pytest.raises(ValueError, match="OCR"):
        parse_pdf(pdf_factory(pages=[[]]))


def test_typeset_columns_and_figure_labels_keep_correct_sections(tmp_path):
    import pymupdf

    path = tmp_path / "columns.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        # Left column is stored before the right column, as in a typeset LaTeX PDF.
        page.insert_text((50, 70), "2", fontname="hebo")
        page.insert_text((70, 70), "OBSERVATIONS AND DATA ANALYSIS", fontname="hebo")
        page.insert_text((50, 110), "Radio observing setup.")
        page.insert_text((50, 400), "3 Results", fontname="hebo")
        page.insert_text((50, 440), "The measurements begin here.")
        page.insert_text((330, 110), "Right column continues the results.")
        page.insert_text((330, 180), "5.5 GHz radio luminosity")
        page.insert_text((330, 220), "Further discussion of the measurements.")
        doc.save(path)
    blocks = parse_pdf(path).blocks
    assert blocks[0].section == "2 OBSERVATIONS AND DATA ANALYSIS"
    right = next(block for block in blocks if "Right column" in block.text)
    assert right.section == "3 Results"
    assert blocks[-1].section == "3 Results"
    assert all(block.section != "5.5 GHz radio luminosity" for block in blocks)


def test_catalogue_reader_supports_csv(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("name,ra_deg,dec_deg\nGX 9+9,262.934,-16.961\nGX 3+1,266.976,-26.565\n")
    result = read_catalogue(path, preview_rows=1)
    assert result["format"] == "csv"
    assert result["columns"] == ["name", "ra_deg", "dec_deg"]
    assert result["row_count"] == 2
    assert result["preview"] == [{"name": "GX 9+9", "ra_deg": "262.934", "dec_deg": "-16.961"}]


def test_catalogue_reader_supports_fits_when_astropy_is_installed(tmp_path):
    table_module = pytest.importorskip("astropy.table")
    path = tmp_path / "sample.fits"
    table = table_module.Table({"name": ["GX 9+9"], "flux_mjy": [1.7]})
    table.write(path, format="fits")
    result = read_catalogue(path)
    assert result["format"] == "fits"
    assert result["row_count"] == 1
    assert result["columns"] == ["name", "flux_mjy"]


def test_catalogue_reader_supports_ascii_when_astropy_is_installed(tmp_path):
    pytest.importorskip("astropy.table")
    path = tmp_path / "sample.dat"
    path.write_text("name flux_mjy\nGX_9+9 1.7\n")
    result = read_catalogue(path)
    assert result["format"] == "ascii"
    assert result["row_count"] == 1
    assert result["columns"] == ["name", "flux_mjy"]


def test_catalogue_reader_rejects_unknown_extension(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Unsupported catalogue format"):
        read_catalogue(path)
