import pytest
from sqlalchemy.exc import OperationalError

from xrb_mcp.server.main import create_server, safe_database_errors


@pytest.mark.asyncio
async def test_tools_and_resource_templates_registered():
    server = create_server()
    tools = await server.list_tools()
    assert {t.name for t in tools} == {"search_literature", "get_paper", "get_source"}
    assert all(t.annotations.readOnlyHint for t in tools)
    assert len(await server.list_resource_templates()) == 3


def test_driver_errors_are_sanitized():
    @safe_database_errors
    def broken():
        raise OperationalError("secret SQL", {"password": "secret"}, Exception("secret URL"))

    with pytest.raises(ValueError) as error:
        broken()
    assert "secret" not in str(error.value)
