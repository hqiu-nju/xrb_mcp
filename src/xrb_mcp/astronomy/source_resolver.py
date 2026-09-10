from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from xrb_mcp.astronomy.aliases import normalize_alias
from xrb_mcp.database.models import Source, SourceAlias


class UnknownSource(ValueError):
    pass


def resolve_source(session: Session, name: str) -> Source:
    normalized = normalize_alias(name)
    canonical = session.scalar(
        select(Source).where(func.lower(Source.canonical_name) == name.strip().lower())
    )
    if canonical:
        return canonical
    alias = session.scalar(
        select(Source).join(SourceAlias).where(SourceAlias.normalized_alias == normalized)
    )
    if alias:
        return alias
    raise UnknownSource(f"Source {name!r} is not registered; manual identification is required")


def register_source(
    session: Session,
    canonical_name: str,
    aliases: list[str],
    authority: str,
    source_class: str | None = None,
    compact_object_type: str | None = None,
) -> Source:
    """Register reviewed identity data. Conflicting aliases never merge source records."""
    if not authority.strip():
        raise ValueError("An authority or reference is required for source identity")
    session.execute(text("SELECT pg_advisory_xact_lock(827001)"))
    normalized = normalize_alias(canonical_name)
    source = session.scalar(select(Source).where(Source.normalized_name == normalized))
    names = {normalize_alias(n): n.strip() for n in [*aliases, canonical_name]}
    existing = session.scalars(
        select(SourceAlias).where(SourceAlias.normalized_alias.in_(names))
    ).all()
    if any(source is None or alias.source_id != source.id for alias in existing):
        raise ValueError("An alias already belongs to another source; review the identity manually")
    if source is None:
        source = Source(
            canonical_name=canonical_name.strip(),
            normalized_name=normalized,
            authority=authority,
            source_class=source_class,
            compact_object_type=compact_object_type,
        )
        session.add(source)
        session.flush()
    existing_names = {alias.normalized_alias for alias in existing}
    for key, name in names.items():
        if key not in existing_names:
            session.add(
                SourceAlias(
                    source_id=source.id,
                    alias=name,
                    normalized_alias=key,
                    alias_type="canonical" if key == normalized else "alternate",
                    authority=authority,
                )
            )
    session.flush()
    return source
