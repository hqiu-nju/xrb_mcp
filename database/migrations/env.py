from alembic import context

from xrb_mcp.database.connection import get_engine
from xrb_mcp.database.models import Base
from xrb_mcp.server.config import get_settings

if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url.get_secret_value(),
        target_metadata=Base.metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
