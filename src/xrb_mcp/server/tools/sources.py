from xrb_mcp.database.connection import session_scope
from xrb_mcp.retrieval.objects import source_object


def get_source(source: str) -> dict:
    """Resolve a registered canonical name, alias or internal UUID, with identity authority."""
    with session_scope(read_only=True) as session:
        return source_object(session, source)
