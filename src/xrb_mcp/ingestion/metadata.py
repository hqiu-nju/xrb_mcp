import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PaperMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1)
    authors: list[str] = Field(default_factory=list)
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    journal: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    ads_bibcode: str | None = None
    abstract: str | None = None
    source_url: str | None = None
    sources: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
        if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
            raise ValueError("Invalid DOI")
        return value.lower()

    @field_validator("arxiv_id")
    @classmethod
    def normalize_arxiv(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = re.sub(r"^(?:https?://arxiv.org/(?:abs|pdf)/|arxiv:\s*)", "", value, flags=re.I)
        value = re.sub(r"\.pdf$", "", value)
        value = re.sub(r"v\d+$", "", value)
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})", value, flags=re.I):
            raise ValueError("Invalid arXiv identifier")
        return value.lower()


def read_metadata(path: Path) -> PaperMetadata:
    return PaperMetadata.model_validate_json(path.read_text(encoding="utf-8"))
