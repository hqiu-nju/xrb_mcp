import json
import sqlite3

import pytest

from xrb_mcp.scripts.source_catalogues import _read_fits, build_source_catalogue


def test_source_build_preserves_members_and_supplementary_tables(tmp_path):
    fits = pytest.importorskip("astropy.io.fits")
    table = pytest.importorskip("astropy.table")
    first = tmp_path / "LMXB_cat.fits"
    second = tmp_path / "watchdog.fit"
    source_table = table.Table(
        {"Name": ["GX 1+4"], "RAdeg": [263.009], "DEdeg": [-24.745], "Alt_Name": ["V2116 Oph"]}
    )
    extra = table.Table({"Ref": ["1"], "BibCode": ["example-reference"]})
    fits.HDUList(
        [fits.PrimaryHDU(), fits.BinTableHDU(source_table), fits.BinTableHDU(extra)]
    ).writeto(first)
    table.Table(
        {"Name": ["V2116 Oph"], "RAJ2000": ["17 32 02.16"], "DEJ2000": ["-24 44 42.0"]}
    ).write(second, format="fits")
    output = tmp_path / "output"

    report = build_source_catalogue([first, second], output, include_blackcat=False)

    assert report["input_rows"] == 2
    assert report["unique_sources"] == 1
    assert report["duplicate_rows_consolidated"] == 1
    with sqlite3.connect(output / "sources.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM catalogue_rows").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM supplementary_rows").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        raw = json.loads(conn.execute("SELECT row_json FROM catalogue_rows LIMIT 1").fetchone()[0])
        assert raw["Alt_Name"] == "V2116 Oph"
    exported = table.Table.read(output / "sources.fits")
    assert len(exported) == 1
    assert str(exported["ra_deg"].unit) == "deg"
    assert (output / "source_catalogue_report.json").is_file()


def test_failed_input_keeps_previous_build(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    database = output / "sources.db"
    database.write_bytes(b"existing snapshot")
    with pytest.raises(FileNotFoundError):
        build_source_catalogue([tmp_path / "missing.fits"], output, include_blackcat=False)
    assert database.read_bytes() == b"existing snapshot"


def test_ascii_fits_blank_numeric_cell_remains_missing(tmp_path):
    fits = pytest.importorskip("astropy.io.fits")
    path = tmp_path / "liu2005_lmc.fit"
    hdu = fits.TableHDU.from_columns(
        [
            fits.Column(name="Name", format="A20", array=["Example source"]),
            fits.Column(name="RAJ2000", format="A12", array=["12 00 00.0"]),
            fits.Column(name="DEJ2000", format="A12", array=["-12 00 00.0"]),
            fits.Column(name="Vmag", format="F8.2", array=[0.0]),
        ]
    )
    fits.HDUList([fits.PrimaryHDU(), hdu]).writeto(path)
    with fits.open(path) as hdus:
        start = hdus[1].fileinfo()["datLoc"] + hdus[1].columns["Vmag"].start - 1
    with path.open("r+b") as handle:
        handle.seek(start)
        handle.write(b" " * 8)

    _, rows, _ = _read_fits(path)

    assert rows[0]["raw"]["Vmag"] is None
    assert rows[0]["raw"]["_fits_ascii_cells"]["Vmag"] == ""
