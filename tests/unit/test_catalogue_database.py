import sqlite3

from xrb_mcp.scripts.catalogues import build_catalogue_database


def test_build_catalogue_database_loads_csv_rows(tmp_path):
    catalogues_dir = tmp_path / "catalogues"
    catalogues_dir.mkdir()
    (catalogues_dir / "sample.csv").write_text(
        "name,ra_deg,dec_deg\nGX 9+9,262.934,-16.961\nGX 3+1,266.976,-26.565\n",
        encoding="utf-8",
    )
    output = tmp_path / "processed" / "catalogues_basic.db"

    summary = build_catalogue_database(catalogues_dir, output)

    assert summary["catalogues_processed"] == 1
    assert summary["rows_loaded"] == 2
    assert summary["failures"] == []

    with sqlite3.connect(output) as conn:
        (catalogue_count,) = conn.execute("SELECT COUNT(*) FROM catalogues").fetchone()
        (row_count,) = conn.execute("SELECT COUNT(*) FROM catalogue_rows").fetchone()
    assert catalogue_count == 1
    assert row_count == 2