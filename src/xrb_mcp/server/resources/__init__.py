import json

from xrb_mcp.astronomy.ontology import INSTRUMENTS, ONTOLOGY_VERSION, TOPICS, WAVELENGTHS
from xrb_mcp.database.errors import safe_database_errors
from xrb_mcp.database.portable_schema import DATABASE_FILENAME
from xrb_mcp.retrieval.portable import PortableReader
from xrb_mcp.server.config import get_settings
from xrb_mcp.server.tools.literature import get_paper
from xrb_mcp.server.tools.sources import get_source


def register_resources(mcp) -> None:
    @mcp.resource("xrb://dataset")
    @safe_database_errors
    def dataset_resource() -> str:
        settings = get_settings()
        if settings.database_mode != "portable":
            return json.dumps({"database_mode": "postgresql", "portable_snapshot": False})
        with PortableReader(settings.dataset_dir / DATABASE_FILENAME) as reader:
            return json.dumps(reader.dataset_info(include_catalogues=True))

    @mcp.resource("xrb://sources/{source_id}")
    @safe_database_errors
    def source_resource(source_id: str) -> str:
        return json.dumps(get_source(source_id))

    @mcp.resource("xrb://papers/{paper_id}")
    @safe_database_errors
    def paper_resource(paper_id: str) -> str:
        return json.dumps(get_paper(paper_id))

    @mcp.resource("xrb://ontology/{vocabulary}")
    def ontology_resource(vocabulary: str) -> str:
        ontologies = {"wavelengths": WAVELENGTHS, "instruments": INSTRUMENTS, "topics": TOPICS}
        if vocabulary not in ontologies:
            raise ValueError("Unknown ontology; choose wavelengths, instruments or topics")
        return json.dumps({"version": ONTOLOGY_VERSION, "terms": ontologies[vocabulary]})
