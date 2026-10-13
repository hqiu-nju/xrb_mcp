import hashlib

import httpx
import pytest

from xrb_mcp.ingestion.blackcat import BLACKCAT_URL, fetch_blackcat, parse_blackcat_html


def listing_html(name="MAXI J1820+070<br>ASASSN-18ey = V3721 Oph", identifier="63"):
    headers = [
        "ID",
        "Name<br>(Counterpart)",
        "RA",
        "DEC",
        "ℓ",
        "b",
        "Outburst",
        "Quiescence",
        "d [kpc]",
        "Flux",
        "Porb [h]",
    ]
    values = [
        f'<a href="info.php?id={identifier}">{identifier}</a>',
        f'<a href="info.php?id={identifier}">{name}</a>',
        "18:20:21.94",
        "+07:11:07.19",
        "035.8535506",
        "10.1591562",
        "V∼14",
        "i’&gt;24.1",
        "&gt;3 / 2.2<sup>+0.5</sup><sub>-0.6</sub>",
        "2.26E-07",
        "&lt;8.2",
    ]
    return (
        "<table><tr>"
        + "".join(f"<th>{header}</th>" for header in headers)
        + '</tr><tbody><tr style="font-weight:bold">'
        + "".join(f"<td>{value}</td>" for value in values)
        + "</tr></tbody></table><p>Last modified: 22 September 2025.</p>"
    )


def test_names_coordinates_limits_and_all_raw_fields():
    (row,) = parse_blackcat_html(listing_html())
    assert row["name"] == "MAXI J1820+070"
    assert row["aliases"] == ["ASASSN-18ey", "V3721 Oph"]
    assert row["ra"] == "18:20:21.94"
    assert row["dec"] == "+07:11:07.19"
    assert row["blackcat_id"] == "63"
    assert row["source_url"] == "https://www.astro.puc.cl/BlackCAT/info.php?id=63"
    assert row["distance_kpc_text"] == ">3 / 2.2^{+0.5}_{-0.6}"
    assert row["orbital_period_hours_text"] == "<8.2"
    assert row["quiescent_magnitude_text"] == "i’>24.1"
    assert len(row["raw_fields"]) == 11
    assert row["row_style"] == "font-weight:bold"
    assert row["compact_object_type"] == "BH candidate"


def test_empty_counterpart_and_repeated_tbody():
    html = listing_html(name="Swift J1728.9-3613<br>")
    second = listing_html(name="Other source<br>Alternative source", identifier="64")
    second_body = second[second.index("<tbody>") : second.index("</table>")]
    html = html.replace("</table>", second_body + "</table>")
    row, other = parse_blackcat_html(html, "https://example.org/catalog/transients.php")
    assert row["aliases"] == []
    assert row["source_url"] == "https://example.org/catalog/info.php?id=63"
    assert other["blackcat_id"] == "64"
    assert other["aliases"] == ["Alternative source"]


def test_duplicate_ids_are_rejected():
    html = listing_html()
    body = html[html.index("<tbody>") : html.index("</table>")]
    with pytest.raises(ValueError, match="repeated BlackCAT ID"):
        parse_blackcat_html(html.replace("</table>", body + "</table>"))


@pytest.mark.parametrize("html", ["<html>Maintenance</html>", "<table></table>"])
def test_unexpected_document_is_rejected(html):
    with pytest.raises(ValueError, match="BlackCAT source table"):
        parse_blackcat_html(html)


def test_invalid_schema_is_rejected():
    with pytest.raises(ValueError, match="schema"):
        parse_blackcat_html(
            "<table><tr><th>ID</th><th>Name</th><th>RA</th><th>DEC</th></tr></table>"
        )


def test_fetch_saves_verified_snapshot_with_provenance(tmp_path, monkeypatch):
    html = listing_html()
    response = httpx.Response(
        200,
        text=html,
        headers={"last-modified": "Yesterday"},
        request=httpx.Request("GET", BLACKCAT_URL),
    )
    monkeypatch.setattr("xrb_mcp.ingestion.blackcat.httpx.get", lambda *args, **kwargs: response)
    path = tmp_path / "snapshot.html"
    metadata = fetch_blackcat(path)
    assert path.read_text() == html
    assert metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert metadata["page_last_modified"] == "22 September 2025"
    assert metadata["http_last_modified"] == "Yesterday"
    assert metadata["row_count"] == 1
    assert metadata["retrieved_at"].endswith("+00:00")


def test_fetch_invalid_page_does_not_overwrite_snapshot(tmp_path, monkeypatch):
    response = httpx.Response(200, text="Maintenance", request=httpx.Request("GET", BLACKCAT_URL))
    monkeypatch.setattr("xrb_mcp.ingestion.blackcat.httpx.get", lambda *args, **kwargs: response)
    path = tmp_path / "snapshot.html"
    path.write_text("existing")
    with pytest.raises(ValueError):
        fetch_blackcat(path)
    assert path.read_text() == "existing"
