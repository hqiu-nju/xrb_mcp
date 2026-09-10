import json

from xrb_mcp.astronomy.ontology import INSTRUMENTS, ONTOLOGY_VERSION, TOPICS, WAVELENGTHS
from xrb_mcp.database.errors import safe_database_errors
from xrb_mcp.server.tools.literature import get_paper
from xrb_mcp.server.tools.sources import get_source


def register_resources(mcp) -> None:
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
