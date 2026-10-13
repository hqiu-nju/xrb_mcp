"""Extract catalogue identities and merge only defensible source associations.

Names are identifiers, not fuzzy text. Coordinate matches are mutual, isolated
neighbours across catalogues; an ambiguous association stays in the review list.
The original rows are retained by the ingestion caller as the evidence record.
"""

import hashlib
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from xrb_mcp.astronomy.aliases import normalize_alias

_MISSING = {"", "--", "none", "null", "nan", "n/a"}
_PRIORITY = {
    "hmxb_cat.fits": 0,
    "lmxb_cat.fits": 0,
    "blackcat": 1,
    "watchdog.fit": 2,
    "liu2006.fit": 3,
    "liu2005_lmc.fit": 4,
    "liu2000_lmxb.fit": 5,
}
_ALIAS_CONFLICT_ARCSEC = 120.0
_UNRESOLVED_IDENTITY_REASONS = {
    "ambiguous_alias_within_catalogue",
    "ambiguous_liu_designation",
    "liu_designation_without_positional_corroboration",
    "multiple_rows_same_catalogue",
    "cluster_coordinate_conflict",
}
# Liu (2000), CDS V/106, suppresses mission prefixes in its Name column.
# This exception applies only to that table and an identical coordinate-name
# suffix with positional corroboration. It is never general prefix stripping.
_LIU_DESIGNATION = re.compile(r"J?\d{4}(?:\.\d+)?[+-]\d{2,6}(?:\.\d+)?", re.I)
_MISSION_DESIGNATION = re.compile(
    r"(?:4U|1U|2U|1A|2A|3A|1E|2E|1H|2S|H|GS|GRS|GRO|XTE|SAX|RX|"
    r"MXB|XB|SLX|KS|EXO)\s*(J?\d{4}(?:\.\d+)?[+-]\d{2,6}(?:\.\d+)?)",
    re.I,
)


def _text(value: Any) -> str | None:
    if value is None or getattr(value, "mask", None) is True:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return None if value.casefold() in _MISSING else value


def _number(value: Any) -> float | None:
    if value is None or getattr(value, "mask", None) is True:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _angle(value: Any, *, hourangle: bool) -> float | None:
    """Read decimal degrees or sexagesimal, preserving a negative-zero Dec."""
    number = _number(value)
    if number is not None:
        return number
    value = _text(value)
    if value is None:
        return None
    from astropy import units as u
    from astropy.coordinates import Angle

    try:
        return float(Angle(value, unit=u.hourangle if hourangle else u.deg).degree)
    except (ValueError, TypeError):
        return None


def _clean_aliases(names: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for name in names:
        if value := _text(name):
            unique.setdefault(normalize_alias(value), value)
    return list(unique.values())


def _compact_object_type(raw: dict[str, Any], catalogue: str) -> str | None:
    explicit = _text(raw.get("compact_object_type"))
    if explicit:
        return explicit
    if catalogue == "watchdog.fit":
        tokens = {_text(token) for token in str(raw.get("Type", "")).split(",")}
        if "BHC" in tokens:
            return "BH candidate"
        if "BH" in tokens:
            return "BH"
    tokens = re.split(r"[,;|\s]+", _text(raw.get("Xray_Type")) or "")
    # The modern catalogue ReadMes define BH as a candidate flag.
    for marker, label in [
        ("BH?", "BH candidate"),
        ("BH", "BH candidate"),
        ("QNS?", "NS candidate"),
        ("QNS", "NS"),
    ]:
        if marker in tokens:
            return label
    return None


def extract_source_row(catalogue: str, row_index: int, raw: dict[str, Any]) -> dict[str, Any]:
    """Extract identity fields from one of the supplied FITS/BlackCAT rows.

    All FITS RAJ2000/DEJ2000 columns supplied here contain J2000 sexagesimal
    coordinates. PosErr and WATCHDOG coordinate errors are already arcseconds.
    No precision or compact-object confirmation is inferred from a name.
    """
    key = Path(catalogue).name.lower()
    name = _text(raw.get("Name")) or _text(raw.get("name"))
    if not name:
        raise ValueError(f"Missing source name in {catalogue} row {row_index}")
    aliases = [name]
    tentative_aliases = []
    for field in ("Alt_Name", "alt_name", "OName", "IDS", "aliases"):
        value = raw.get(field)
        if isinstance(value, (list, tuple)):
            additions = [item for item in value if isinstance(item, str)]
        elif text_value := _text(value):
            # Modern Alt_Name is one identifier; IDS/OName have explicit lists.
            separator = r"[,;|]" if field == "IDS" else r"[;|]"
            additions = re.split(separator, text_value)
        else:
            continue
        if field == "IDS":
            # SIMBAD's V* and NAME are identifier presentation categories,
            # not part of the star's conventional name. Retain both forms.
            plain = []
            for item in additions:
                match = re.fullmatch(r"(?:V\*|NAME)\s+(.+)", item.strip())
                if match:
                    plain.append(match[1])
            additions.extend(plain)
        aliases.extend(additions)
        if field == "IDS" and key == "hmxb_cat.fits" and _number(raw.get("ID_Flag")) != 0:
            tentative_aliases.extend(additions)
    if "RAdeg" in raw or "DEdeg" in raw:
        ra, dec = _number(raw.get("RAdeg")), _number(raw.get("DEdeg"))
        origin = "ICRS" if key in {"hmxb_cat.fits", "lmxb_cat.fits"} else "catalogue RAdeg/DEdeg"
    elif "ra_deg" in raw or "dec_deg" in raw:
        ra, dec = _number(raw.get("ra_deg")), _number(raw.get("dec_deg"))
        origin = _text(raw.get("coordinate_origin")) or "catalogue decimal degrees"
    else:
        ra = _angle(raw.get("RAJ2000", raw.get("ra")), hourangle=True)
        dec = _angle(raw.get("DEJ2000", raw.get("dec")), hourangle=False)
        origin = "J2000"
    if ra is None or dec is None or not (0 <= ra < 360 and -90 <= dec <= 90):
        ra, dec, origin = None, None, None
    uncertainty = _number(raw.get("PosErr", raw.get("pos_err_arcsec")))
    if key == "watchdog.fit":
        # WATCHDOG can repeat an error radius in both columns, or transform
        # an error ellipse into a box. Do not assume independent Gaussians.
        errors = [_number(raw.get(field)) for field in ("e_RAJ2000", "e_DEJ2000")]
        known = [value for value in errors if value is not None and value > 0]
        uncertainty = max(known) if known else None
    if uncertainty is not None and uncertainty <= 0:
        uncertainty = None
    source_class = {
        "hmxb_cat.fits": "HMXB",
        "liu2006.fit": "HMXB",
        "liu2005_lmc.fit": "HMXB",
        "lmxb_cat.fits": "LMXB",
        "liu2000_lmxb.fit": "LMXB",
        "watchdog.fit": "BH-XRB",
        "blackcat": "BH-XRB",
    }.get(key) or _text(raw.get("source_class"))
    compact_object = _compact_object_type(raw, key)
    bh_status = _text(raw.get("bh_status")) or (
        "confirmed"
        if compact_object == "BH"
        else ("candidate" if compact_object == "BH candidate" else None)
    )
    all_aliases = _clean_aliases(aliases)
    tentative = {normalize_alias(alias) for alias in _clean_aliases(tentative_aliases)}
    explicit = {normalize_alias(name)}
    for field in ("Alt_Name", "alt_name"):
        if value := _text(raw.get(field)):
            explicit.add(normalize_alias(value))
    return {
        "catalogue": catalogue,
        "row_index": row_index,
        "name": name,
        "aliases": all_aliases,
        "match_aliases": [
            alias
            for alias in all_aliases
            if normalize_alias(alias) not in tentative or normalize_alias(alias) in explicit
        ],
        "ra_deg": ra,
        "dec_deg": dec,
        "pos_err_arcsec": uncertainty,
        "source_class": source_class,
        "compact_object_type": compact_object,
        "bh_status": bh_status,
        "coordinate_origin": origin,
        "raw": raw,
    }


def _separation(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    if any(row.get(field) is None for row in (left, right) for field in ("ra_deg", "dec_deg")):
        return None
    ra1, dec1, ra2, dec2 = (
        math.radians(row[field]) for row in (left, right) for field in ("ra_deg", "dec_deg")
    )
    haversine = math.sin((dec2 - dec1) / 2) ** 2
    haversine += math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    return math.degrees(2 * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))) * 3600


def _priority(row: dict[str, Any]) -> tuple[int, str, int]:
    catalogue = Path(row["catalogue"]).name.lower()
    return _PRIORITY.get(catalogue, 10), catalogue, row["row_index"]


def _coordinate_row(members: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [
        row for row in members if row.get("ra_deg") is not None and row.get("dec_deg") is not None
    ]
    if not valid:
        return None
    # Prefer the current compilations over legacy positions, then select the
    # smallest published error within that priority tier. Decimal places are
    # never interpreted as an uncertainty.
    return min(
        valid,
        key=lambda row: (
            _priority(row)[0],
            row.get("pos_err_arcsec") is None,
            row.get("pos_err_arcsec") if row.get("pos_err_arcsec") is not None else math.inf,
            _priority(row),
        ),
    )


def deduplicate_sources(
    rows: list[dict[str, Any]],
    match_radius_arcsec: float = 5.0,
) -> dict[str, list[dict[str, Any]]]:
    """Merge exact aliases, corroborated Liu names, and isolated positional pairs.

    Unambiguous cross-catalogue aliases survive old coordinate disagreements,
    which are still reported for review. An alias repeated within one catalogue
    is ambiguous. Positional
    associations are evaluated once, after name matches, so they cannot form
    transitive proximity chains. Nearby same-catalogue objects also count as
    crowding, even though they are never matched by position alone. Liu (2000)
    globular-cluster entries require named identity evidence because a cluster
    position can coincide with a different resolved modern member.
    """
    if not math.isfinite(match_radius_arcsec) or match_radius_arcsec <= 0:
        raise ValueError("match_radius_arcsec must be finite and positive")
    keys = [(row["catalogue"], row["row_index"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Catalogue row keys must be unique")
    parent = list(range(len(rows)))
    members = {i: {i} for i in range(len(rows))}
    matches: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    review_keys: set[tuple[int, int, str]] = set()
    unresolved_identity: dict[int, set[str]] = defaultdict(set)

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def record(left: int, right: int, method: str, shared: list[str]) -> dict[str, Any]:
        return {
            "left_catalogue": rows[left]["catalogue"],
            "left_row_index": rows[left]["row_index"],
            "right_catalogue": rows[right]["catalogue"],
            "right_row_index": rows[right]["row_index"],
            "method": method,
            "separation_arcsec": _separation(rows[left], rows[right]),
            "shared_aliases": shared,
        }

    def flag(
        left: int,
        right: int,
        reason: str,
        method: str,
        shared: list[str],
        **context: Any,
    ) -> None:
        if reason in _UNRESOLVED_IDENTITY_REASONS:
            unresolved_identity[left].add(reason)
            unresolved_identity[right].add(reason)
        identity = (*sorted((left, right)), reason)
        if identity not in review_keys:
            review_keys.add(identity)
            review.append({**record(left, right, method, shared), "reason": reason, **context})

    def union(left: int, right: int, method: str, shared: list[str]) -> bool:
        a, b = root(left), root(right)
        if a == b:
            matches.append(record(left, right, method, shared))
            return True
        for i in members[a]:
            for j in members[b]:
                distance = _separation(rows[i], rows[j])
                if (
                    distance is not None
                    and distance >= _ALIAS_CONFLICT_ARCSEC
                    and method != "alias_exact"
                ):
                    flag(left, right, "cluster_coordinate_conflict", method, shared)
                    return False
                if rows[i]["catalogue"] == rows[j]["catalogue"]:
                    overlap = {normalize_alias(alias) for alias in rows[i]["aliases"]} & {
                        normalize_alias(alias) for alias in rows[j]["aliases"]
                    }
                    if (
                        not overlap
                        or distance is None
                        or distance > match_radius_arcsec
                        or normalize_alias(rows[i]["name"]) != normalize_alias(rows[j]["name"])
                    ):
                        flag(left, right, "multiple_rows_same_catalogue", method, shared)
                        return False
        if method == "alias_exact":
            for i in members[a]:
                for j in members[b]:
                    distance = _separation(rows[i], rows[j])
                    if distance is not None and distance >= _ALIAS_CONFLICT_ARCSEC:
                        flag(i, j, "coordinate_disagreement", method, shared)
        if b < a:
            a, b = b, a
        parent[b] = a
        members[a] |= members.pop(b)
        matches.append(record(left, right, method, shared))
        return True

    alias_rows: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        for alias in {normalize_alias(value) for value in row.get("match_aliases", row["aliases"])}:
            alias_rows[alias].append(index)
    ambiguous_aliases = {
        alias
        for alias, indices in alias_rows.items()
        if len({rows[index]["catalogue"] for index in indices}) < len(indices)
    }
    pairs: dict[tuple[int, int], list[str]] = defaultdict(list)
    for alias, indices in sorted(alias_rows.items()):
        for offset, left in enumerate(indices):
            for right in indices[offset + 1 :]:
                pairs[left, right].append(alias)
    for (left, right), shared in sorted(pairs.items()):
        unambiguous = [alias for alias in shared if alias not in ambiguous_aliases]
        if not unambiguous:
            flag(left, right, "ambiguous_alias_within_catalogue", "alias_exact", shared)
        else:
            union(left, right, "alias_exact", unambiguous)

    # The prefix omission is specific to Liu (2000), not a global alias rule.
    designation_pairs: dict[tuple[int, int], tuple[int, int]] = {}
    for left, row in enumerate(rows):
        if Path(row["catalogue"]).name.lower() != "liu2000_lmxb.fit":
            continue
        if not _LIU_DESIGNATION.fullmatch(row["name"]):
            continue
        designation = normalize_alias(row["name"])
        for right, other in enumerate(rows):
            if row["catalogue"] == other["catalogue"] or root(left) == root(right):
                continue
            suffixes = [_MISSION_DESIGNATION.fullmatch(alias) for alias in other["aliases"]]
            if not any(match and normalize_alias(match[1]) == designation for match in suffixes):
                continue
            distance = _separation(row, other)
            if distance is None or distance >= _ALIAS_CONFLICT_ARCSEC:
                flag(
                    left,
                    right,
                    "liu_designation_without_positional_corroboration",
                    "liu2000_designation",
                    [designation],
                )
            else:
                designation_pairs.setdefault(
                    tuple(sorted((root(left), root(right)))), (left, right)
                )
    neighbours: dict[int, set[int]] = defaultdict(set)
    for a, b in designation_pairs:
        neighbours[a].add(b)
        neighbours[b].add(a)
    for (a, b), (left, right) in sorted(designation_pairs.items()):
        shared = [normalize_alias(rows[left]["name"])]
        if len(neighbours[a]) == len(neighbours[b]) == 1:
            union(left, right, "liu2000_designation", shared)
        else:
            flag(left, right, "ambiguous_liu_designation", "liu2000_designation", shared)

    positions = {key: _coordinate_row([rows[i] for i in value]) for key, value in members.items()}
    neighbours = defaultdict(set)
    positional_pairs: list[tuple[int, int]] = []
    for offset, a in enumerate(sorted(members)):
        for b in sorted(members)[offset + 1 :]:
            if positions[a] is None or positions[b] is None:
                continue
            distance = _separation(positions[a], positions[b])
            if distance is not None and distance <= match_radius_arcsec:
                neighbours[a].add(b)
                neighbours[b].add(a)
                if {rows[i]["catalogue"] for i in members[a]}.isdisjoint(
                    rows[i]["catalogue"] for i in members[b]
                ):
                    positional_pairs.append((a, b))
    for a, b in positional_pairs:
        left = next(i for i in members[a] if rows[i] is positions[a])
        right = next(i for i in members[b] if rows[i] is positions[b])
        legacy_globular_members = [
            i
            for i in members[a] | members[b]
            if Path(rows[i]["catalogue"]).name.lower() == "liu2000_lmxb.fit"
            and "G" in (_text(rows[i].get("raw", {}).get("Type")) or "").upper()
        ]
        identity_reasons = sorted(
            {reason for i in members[a] | members[b] for reason in unresolved_identity[i]}
        )
        if legacy_globular_members:
            # A legacy globular-cluster position may refer to a cluster or its
            # bright X-ray source rather than one resolved modern member.
            # Matching it to a nearby faint member needs a named identity.
            flag(
                left,
                right,
                "legacy_globular_cluster_position",
                "coordinate",
                [],
                legacy_globular_rows=[
                    {
                        "catalogue": rows[i]["catalogue"],
                        "row_index": rows[i]["row_index"],
                        "catalogue_type": rows[i]["raw"].get("Type"),
                    }
                    for i in sorted(legacy_globular_members)
                ],
            )
        elif identity_reasons:
            flag(
                left,
                right,
                "unresolved_identity_blocks_coordinate_match",
                "coordinate",
                [],
                identity_review_reasons=identity_reasons,
            )
        elif len(neighbours[a]) == len(neighbours[b]) == 1:
            union(left, right, "coordinate_mutual_unique", [])
        else:
            flag(left, right, "ambiguous_coordinate_neighbourhood", "coordinate", [])

    sources = []
    for indices in members.values():
        group = sorted((rows[i] for i in indices), key=_priority)
        position = _coordinate_row(group)
        member_keys = sorted((row["catalogue"], row["row_index"]) for row in group)
        stable_identity = "\n".join(f"{catalogue}\t{index}" for catalogue, index in member_keys)
        source_id = "xrb-" + hashlib.sha256(stable_identity.encode()).hexdigest()[:20]
        methods = sorted(
            {
                match["method"]
                for match in matches
                if (match["left_catalogue"], match["left_row_index"]) in member_keys
                and (match["right_catalogue"], match["right_row_index"]) in member_keys
            }
        )
        statuses = {row.get("bh_status") for row in group} - {None}
        bh_status = (
            "confirmed"
            if "confirmed" in statuses
            else (
                "candidate_or_confirmed_unspecified"
                if "candidate_or_confirmed_unspecified" in statuses
                else ("candidate" if "candidate" in statuses else None)
            )
        )
        sources.append(
            {
                "source_id": source_id,
                "canonical_name": group[0]["name"],
                "aliases": _clean_aliases([alias for row in group for alias in row["aliases"]]),
                "ra_deg": position["ra_deg"] if position else None,
                "dec_deg": position["dec_deg"] if position else None,
                "pos_err_arcsec": position.get("pos_err_arcsec") if position else None,
                "source_classes": sorted(
                    {row["source_class"] for row in group if row.get("source_class")}
                ),
                "compact_object_types": sorted(
                    {row["compact_object_type"] for row in group if row.get("compact_object_type")}
                ),
                "bh_status": bh_status,
                "coordinate_origin": position["coordinate_origin"] if position else None,
                "coordinate_member_key": (position["catalogue"], position["row_index"])
                if position
                else None,
                "member_keys": member_keys,
                "match_methods": methods,
            }
        )
    return {
        "sources": sorted(
            sources,
            key=lambda source: (normalize_alias(source["canonical_name"]), source["source_id"]),
        ),
        "matches": matches,
        "review": review,
    }
