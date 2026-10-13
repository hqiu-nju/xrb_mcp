import math

import pytest

from xrb_mcp.astronomy.catalogue_merge import deduplicate_sources, extract_source_row


def source(catalogue, index, name, ra=None, dec=None, **raw):
    return extract_source_row(
        catalogue,
        index,
        {
            "name": name,
            "ra_deg": ra,
            "dec_deg": dec,
            **raw,
        },
    )


def test_extract_sexagesimal_sign_and_alias_delimiters():
    row = extract_source_row(
        "watchdog.fit",
        4,
        {
            "Name": "  XTE J1234-0001 ",
            "OName": "Alpha;Beta|Gamma",
            "RAJ2000": "12 34 56.70",
            "DEJ2000": "-00 01 02.3",
            "e_RAJ2000": 0.2,
            "e_DEJ2000": 0.4,
            "Type": "BHC,T",
        },
    )
    assert row["name"] == "XTE J1234-0001"
    assert row["aliases"] == ["XTE J1234-0001", "Alpha", "Beta", "Gamma"]
    assert row["ra_deg"] == pytest.approx(188.73625)
    assert row["dec_deg"] == pytest.approx(-0.0173055556)
    assert row["pos_err_arcsec"] == 0.4
    assert row["compact_object_type"] == "BH candidate"
    assert row["bh_status"] == "candidate"


def test_extract_ids_missing_values_and_tentative_counterparts():
    row = extract_source_row(
        "HMXB_cat.fits",
        1,
        {
            "Name": b"IGR J12345+6789",
            "Alt_Name": "None",
            "IDS": "IGR J12345+6789, Alpha|Beta;--",
            "ID_Flag": 1,
            "RAdeg": 123.0,
            "DEdeg": -45.0,
            "PosErr": float("nan"),
        },
    )
    assert row["aliases"] == ["IGR J12345+6789", "Alpha", "Beta"]
    assert row["match_aliases"] == ["IGR J12345+6789"]
    assert row["pos_err_arcsec"] is None
    assert row["coordinate_origin"] == "ICRS"


def test_classification_does_not_promote_candidate_flags():
    modern = extract_source_row(
        "LMXB_cat.fits",
        1,
        {
            "Name": "A",
            "RAdeg": 1.0,
            "DEdeg": 2.0,
            "Xray_Type": "BH,T",
        },
    )
    watchdog = extract_source_row("watchdog.fit", 1, {"Name": "B", "Type": "BH,T"})
    magellanic = extract_source_row("liu2005_lmc.fit", 1, {"Name": "C", "Type": "U"})
    assert modern["source_class"] == "LMXB"
    assert modern["bh_status"] == "candidate"
    assert watchdog["bh_status"] == "confirmed"
    assert magellanic["source_class"] == "HMXB"
    assert magellanic["compact_object_type"] is None


def test_blackcat_unspecified_confirmation_status_survives_extraction_and_merge():
    blackcat = extract_source_row(
        "blackcat",
        1,
        {
            "name": "A",
            "ra": "01 02 03",
            "dec": "+04 05 06",
            "compact_object_type": "BH candidate",
            "bh_status": "candidate_or_confirmed_unspecified",
        },
    )
    modern = source("LMXB_cat.fits", 1, "A", Xray_Type="BH")
    assert blackcat["bh_status"] == "candidate_or_confirmed_unspecified"
    assert deduplicate_sources([blackcat, modern])["sources"][0]["bh_status"] == (
        "candidate_or_confirmed_unspecified"
    )
    watchdog = extract_source_row("watchdog.fit", 1, {"Name": "A", "Type": "BH,T"})
    assert deduplicate_sources([blackcat, watchdog])["sources"][0]["bh_status"] == "confirmed"


def test_missing_or_invalid_coordinates_stay_missing():
    row = source("blackcat", 1, "A", float("nan"), 3.0)
    assert row["ra_deg"] is row["dec_deg"] is row["coordinate_origin"] is None
    row = source("blackcat", 2, "B", 3.0, -91.0)
    assert row["ra_deg"] is None
    with pytest.raises(ValueError, match="Missing source name"):
        extract_source_row("blackcat", 3, {"name": "--"})


def test_exact_alias_ignores_case_and_spacing_but_preserves_sign():
    rows = [
        source("a", 1, "XTE J1234+56"),
        source("b", 1, "xte  j1234+56"),
        source("c", 1, "XTE J1234-56"),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 2
    assert result["matches"][0]["method"] == "alias_exact"


def test_unique_exact_identity_merges_large_offset_with_warning_and_modern_position():
    rows = [
        source("watchdog.fit", 1, "Swift J1357.2-0933", 210.0, -9.0, pos_err_arcsec=0.01),
        source("LMXB_cat.fits", 1, "Swift J1357.2-0933", 210.2, -9.0, pos_err_arcsec=0.1),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["ra_deg"] == 210.2
    assert result["sources"][0]["coordinate_member_key"] == ("LMXB_cat.fits", 1)
    assert result["review"][0]["reason"] == "coordinate_disagreement"


def test_duplicated_liu_name_never_identifies_both_objects():
    rows = [
        source("liu2000_lmxb.fit", 83, "1742-294", 266.4, -29.45),
        source("liu2000_lmxb.fit", 90, "1742-294", 266.526, -29.518),
        source("a", 1, "1742-294"),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 3
    assert all(entry["reason"] == "ambiguous_alias_within_catalogue" for entry in result["review"])


def test_alias_collision_with_competing_same_catalogue_objects_stays_split():
    rows = [
        source("LMXB_cat.fits", 171, "Granat 1737-309", 265.0, -31.0, aliases=["GRS 1737-31"]),
        source("LMXB_cat.fits", 172, "GRS 1737-31", 265.06, -31.06),
        source("watchdog.fit", 1, "GRS 1737-31", 265.06, -31.06),
    ]
    result = deduplicate_sources(rows)
    # The ambiguous identifier cannot be resolved by positional fallback.
    assert len(result["sources"]) == 3
    assert any(entry["reason"] == "ambiguous_alias_within_catalogue" for entry in result["review"])
    assert not any(
        {("LMXB_cat.fits", 171), ("LMXB_cat.fits", 172)} <= set(entry["member_keys"])
        for entry in result["sources"]
    )


def test_isolated_cross_catalogue_coordinate_pair_merges():
    rows = [source("a", 1, "A", 10.0, -20.0), source("b", 1, "B", 10.0 + 2 / 3600, -20.0)]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 1
    assert result["matches"][0]["method"] == "coordinate_mutual_unique"
    assert result["matches"][0]["separation_arcsec"] == pytest.approx(
        2 * math.cos(math.radians(20))
    )


def test_crowded_same_catalogue_neighbors_prevent_positional_merge():
    rows = [
        source("a", 1, "A", 10.0, 0.0),
        source("a", 2, "B", 10.0 + 2 / 3600, 0.0),
        source("b", 1, "C", 10.0 + 1 / 3600, 0.0),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 3
    assert len(result["review"]) == 2
    assert all(
        entry["reason"] == "ambiguous_coordinate_neighbourhood" for entry in result["review"]
    )


def test_coordinate_chain_is_never_transitively_merged():
    rows = [
        source("a", 1, "A", 10.0, 0.0),
        source("b", 1, "B", 10.0 + 4 / 3600, 0.0),
        source("c", 1, "C", 10.0 + 8 / 3600, 0.0),
    ]
    assert len(deduplicate_sources(rows)["sources"]) == 3


def test_same_catalogue_coordinates_alone_never_merge():
    rows = [source("a", 1, "A", 10.0, 0.0), source("a", 2, "B", 10.0, 0.0)]
    assert len(deduplicate_sources(rows)["sources"]) == 2


def test_liu_prefix_exception_is_unique_and_positionally_corroborated():
    rows = [
        source("liu2000_lmxb.fit", 1, "0620-003", 95.0, -0.3),
        source("LMXB_cat.fits", 1, "3A 0620-003", 95.0 + 20 / 3600, -0.3),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 1
    assert result["matches"][0]["method"] == "liu2000_designation"
    assert result["sources"][0]["canonical_name"] == "3A 0620-003"
    rows[1] = source("LMXB_cat.fits", 1, "Unrecognised 0620-003", 95.0 + 20 / 3600, -0.3)
    assert len(deduplicate_sources(rows)["sources"]) == 2


def test_liu_prefix_exception_requires_coordinates():
    rows = [source("liu2000_lmxb.fit", 1, "0620-003"), source("LMXB_cat.fits", 1, "3A 0620-003")]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 2
    assert result["review"][0]["reason"] == "liu_designation_without_positional_corroboration"


def test_tentative_counterpart_alias_does_not_identify_source():
    tentative = extract_source_row(
        "HMXB_cat.fits",
        1,
        {
            "Name": "A",
            "IDS": "Star 1",
            "ID_Flag": 1,
        },
    )
    assert len(deduplicate_sources([tentative, source("b", 1, "Star 1")])["sources"]) == 2


def test_simbad_presentation_prefixes_add_plain_aliases_without_losing_originals():
    row = extract_source_row(
        "HMXB_cat.fits",
        1,
        {
            "Name": "4U 0352+309",
            "IDS": "V* X Per,NAME Interesting Star,AB* Double",
            "ID_Flag": 0,
        },
    )
    assert row["aliases"] == [
        "4U 0352+309",
        "V* X Per",
        "NAME Interesting Star",
        "AB* Double",
        "X Per",
        "Interesting Star",
    ]
    assert "Double" not in row["aliases"]
    assert len(deduplicate_sources([row, source("b", 1, "X Per")])["sources"]) == 1


def test_derived_simbad_aliases_preserve_tentative_counterpart_exclusion():
    row = extract_source_row(
        "HMXB_cat.fits",
        1,
        {
            "Name": "A",
            "IDS": "V* X Per,NAME Interesting Star",
            "ID_Flag": 1,
        },
    )
    assert "X Per" in row["aliases"]
    assert "Interesting Star" in row["aliases"]
    assert row["match_aliases"] == ["A"]
    assert len(deduplicate_sources([row, source("b", 1, "X Per")])["sources"]) == 2


def test_ambiguous_liu_designation_cannot_attach_to_unrelated_nearby_source():
    rows = [
        source("liu2000_lmxb.fit", 102, "1745-203", 267.0, -20.0),
        source("liu2000_lmxb.fit", 109, "J1748.9-2021", 267.0 + 30 / 3600, -20.0),
        source(
            "LMXB_cat.fits",
            235,
            "SAX J1748.9-2021",
            267.0 + 30 / 3600,
            -20.0,
            aliases=["4U 1745-203"],
        ),
        source("LMXB_cat.fits", 243, "[ZGV2011] 3", 267.0 + 0.5 / 3600, -20.0),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 4
    assert any(entry["reason"] == "ambiguous_liu_designation" for entry in result["review"])
    rejected = next(
        entry
        for entry in result["review"]
        if entry["reason"] == "unresolved_identity_blocks_coordinate_match"
        and entry["left_row_index"] == 102
    )
    assert "ambiguous_liu_designation" in rejected["identity_review_reasons"]
    assert not result["matches"]


def test_conflicting_liu_name_cannot_attach_to_different_source_by_position():
    rows = [
        source("liu2000_lmxb.fit", 1, "1745-248", 267.0, -24.0),
        source("LMXB_cat.fits", 1, "EXO 1745-248", 267.5, -24.0),
        source("LMXB_cat.fits", 2, "Cluster Member 6", 267.0, -24.0),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 3
    assert any(
        entry["reason"] == "unresolved_identity_blocks_coordinate_match"
        for entry in result["review"]
    )


def test_legacy_globular_position_cannot_identify_a_resolved_faint_member():
    rows = [
        source("liu2000_lmxb.fit", 107, "1747-313", 267.0, -31.0, Type="G"),
        source("LMXB_cat.fits", 254, "[ZGV2011] 5", 267.0 + 0.716 / 3600, -31.0),
        source(
            "LMXB_cat.fits", 255, "GRS 1747-312", 267.0 + 65.51 / 3600, -31.0, aliases=["1747-3116"]
        ),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 3
    assert not result["matches"]
    assert result["review"][0]["reason"] == "legacy_globular_cluster_position"
    assert result["review"][0]["legacy_globular_rows"] == [
        {"catalogue": "liu2000_lmxb.fit", "row_index": 107, "catalogue_type": "G"}
    ]


@pytest.mark.parametrize("match", ["alias_exact", "liu2000_designation"])
def test_legacy_globular_identification_with_explicit_evidence_is_allowed(match):
    modern_name = "1745-248" if match == "alias_exact" else "EXO 1745-248"
    rows = [
        source("liu2000_lmxb.fit", 1, "1745-248", 267.0, -24.0, Type="TGB"),
        source("LMXB_cat.fits", 1, modern_name, 267.0 + 20 / 3600, -24.0),
    ]
    result = deduplicate_sources(rows)
    assert len(result["sources"]) == 1
    assert result["matches"][0]["method"] == match


def test_ra_wraparound_matches_and_source_ids_are_order_independent():
    rows = [source("a", 1, "A", 359.9999, 0), source("b", 1, "B", 0.0001, 0)]
    forward = deduplicate_sources(rows)
    reverse = deduplicate_sources(list(reversed(rows)))
    assert len(forward["sources"]) == 1
    assert forward["sources"] == reverse["sources"]


def test_lowest_known_error_within_modern_tier_and_status_history_are_preserved():
    rows = [
        source("HMXB_cat.fits", 1, "A", 1.0, 2.0, pos_err_arcsec=3.0),
        source("LMXB_cat.fits", 2, "A", 1.001, 2.0, pos_err_arcsec=1.0),
        source("watchdog.fit", 1, "A", 1.0, 2.0, Type="BH,T"),
    ]
    result = deduplicate_sources(rows)["sources"][0]
    assert result["coordinate_member_key"] == ("LMXB_cat.fits", 2)
    assert result["source_classes"] == ["BH-XRB", "HMXB", "LMXB"]
    assert result["bh_status"] == "confirmed"


def test_input_contract_validation():
    with pytest.raises(ValueError, match="positive"):
        deduplicate_sources([], 0)
    duplicate = source("a", 1, "A")
    with pytest.raises(ValueError, match="unique"):
        deduplicate_sources([duplicate, duplicate])
