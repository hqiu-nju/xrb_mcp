from pydantic import BaseModel, ConfigDict, Field, model_validator


class LiteratureFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str | None = None
    source_class: str | None = None
    wavelengths: list[str] = Field(default_factory=list)
    instruments: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    year_min: int | None = Field(default=None, ge=1500, le=2200)
    year_max: int | None = Field(default=None, ge=1500, le=2200)
    collection: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_year_range(self):
        if self.year_min and self.year_max and self.year_min > self.year_max:
            raise ValueError("year_min must not exceed year_max")
        return self
