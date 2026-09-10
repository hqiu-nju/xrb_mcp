import argparse
import json
import logging

from xrb_mcp.astronomy.source_resolver import register_source
from xrb_mcp.database.connection import session_scope
from xrb_mcp.retrieval.objects import source_object


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a manually reviewed source identity")
    parser.add_argument("canonical_name")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument(
        "--authority", required=True, help="Reference or reviewer for identity data"
    )
    parser.add_argument("--source-class")
    parser.add_argument("--compact-object-type")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    with session_scope() as session:
        source = register_source(
            session,
            args.canonical_name,
            args.alias,
            args.authority,
            args.source_class,
            args.compact_object_type,
        )
        result = source_object(session, str(source.id))
    logging.info("source_registered source_id=%s", result["id"])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
