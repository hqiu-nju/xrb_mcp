from xrb_mcp.database.connection import session_scope
from xrb_mcp.database.portable_schema import DATABASE_FILENAME
from xrb_mcp.retrieval.objects import source_object
from xrb_mcp.retrieval.portable import PortableReader
from xrb_mcp.server.config import get_settings


def get_source(source: str) -> dict:
    """Resolve a registered canonical name, alias or internal UUID, with identity authority."""
    settings = get_settings()
    if settings.database_mode == "portable":
        with PortableReader(settings.dataset_dir / DATABASE_FILENAME) as reader:
            return reader.source_object(source)
    with session_scope(read_only=True) as session:
        return source_object(session, source)
