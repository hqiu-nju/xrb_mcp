import re
import unicodedata


def normalize_alias(value: str) -> str:
    """Ignore case/spacing and typographic minus variants, but preserve coordinate signs."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({"−": "-", "–": "-", "—": "-"}))
    normalized = re.sub(r"\s+", "", value)
    if not normalized:
        raise ValueError("Source name must not be empty")
    return normalized
