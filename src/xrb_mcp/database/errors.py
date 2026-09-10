import functools
import logging

from sqlalchemy.exc import SQLAlchemyError


def safe_database_errors(function):
    """Keep database driver details out of both MCP tool and resource responses."""

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except SQLAlchemyError:
            logging.getLogger(__name__).error("Database operation failed in %s", function.__name__)
            raise ValueError(
                "Database unavailable or schema not ready; ask the operator to check it"
            ) from None

    return wrapped
