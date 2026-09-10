import re

from xrb_mcp.astronomy.ontology import INSTRUMENTS, TOPICS, WAVELENGTHS


def contains_term(text: str, term: str) -> bool:
    pattern = re.escape(term).replace(r"\ ", r"\s+")
    return re.search(r"(?<!\w)" + pattern + r"(?!\w)", text, re.I) is not None


def tag_text(text: str) -> dict[str, list[str]]:
    """Heuristic mention tags only; these do not assert a scientific measurement."""
    return {
        key: sorted(
            tag
            for tag, terms in vocabulary.items()
            if any(contains_term(text, term) for term in terms)
        )
        for key, vocabulary in (
            ("wavelengths", WAVELENGTHS),
            ("instruments", INSTRUMENTS),
            ("topics", TOPICS),
        )
    }
