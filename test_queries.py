import json
from pathlib import Path

from query_graph import find_facts, free_search, load_graph


VALID_GEO_SCOPES = {"domestic", "foreign", "mixed", "unknown"}
VALID_QUALITY_STATUSES = {"верно", "частично", "ошибка"}
QUALITY_VALIDATION_PATH = Path("quality_validation.json")


def require_results(name, facts, min_count=1):
    count = len(facts)
    print(f"{name}: {count} facts")
    if count < min_count:
        raise AssertionError(f"{name}: expected at least {min_count} facts, got {count}")
    return facts


def require_fact_fields(name, facts, fields):
    for field in fields:
        if not any(fact.get(field) not in (None, "") for fact in facts):
            raise AssertionError(f"{name}: no facts with field '{field}'")


def print_examples(facts, limit=3):
    for fact in facts[:limit]:
        value = fact.get("result_value")
        unit = fact.get("result_unit") or ""
        value_text = f" = {value} {unit}".strip() if value is not None else ""
        print(
            "  "
            + " | ".join(
                [
                    str(fact.get("material") or "?"),
                    str(fact.get("process") or "?"),
                    f"{fact.get('result_property') or '?'}{value_text}",
                    str(fact.get("year") or "?"),
                    str(fact.get("location_geo") or "?"),
                    str(fact.get("source_file") or "?"),
                ]
            )
        )


def require_graph_extensions(graph):
    yields_edges = [
        data
        for _, _, data in graph.edges(data=True)
        if data.get("edge_type") == "yields"
    ]
    if not yields_edges:
        raise AssertionError("graph has no yields edges")

    invalid_geo = [
        edge.get("geo_scope")
        for edge in yields_edges
        if edge.get("geo_scope") not in VALID_GEO_SCOPES
    ]
    if invalid_geo:
        raise AssertionError(f"invalid geo_scope values on yields edges: {invalid_geo[:5]}")

    expert_nodes = [
        node_id
        for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == "Expert"
    ]
    if not expert_nodes:
        raise AssertionError("expected Expert nodes in graph")

    edge_types = {data.get("edge_type") for _, _, data in graph.edges(data=True)}
    for edge_type in ("from_document", "expert_in", "worked_on"):
        if edge_type not in edge_types:
            raise AssertionError(f"expected edge type {edge_type}")


def require_quality_validation_file():
    if not QUALITY_VALIDATION_PATH.exists():
        raise AssertionError(f"{QUALITY_VALIDATION_PATH} does not exist")

    rows = json.loads(QUALITY_VALIDATION_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise AssertionError("quality_validation.json must be a list")
    if len(rows) < 20:
        raise AssertionError(f"expected at least 20 validation rows, got {len(rows)}")

    required_fields = {
        "status",
        "reviewer",
        "review_date",
        "material",
        "process",
        "result",
        "source_file",
        "source_quote",
        "comment",
    }
    for index, row in enumerate(rows, start=1):
        missing = required_fields - set(row)
        if missing:
            raise AssertionError(f"validation row {index} missing fields: {sorted(missing)}")
        if row.get("status") not in VALID_QUALITY_STATUSES:
            raise AssertionError(f"validation row {index} has invalid status: {row.get('status')}")


def main():
    graph = load_graph()
    if graph is None:
        raise AssertionError("graph.json was not loaded")
    require_graph_extensions(graph)
    require_quality_validation_file()

    all_facts = require_results("all facts", find_facts(), min_count=100)
    require_fact_fields("all facts", all_facts, ["source_file", "confidence"])
    require_fact_fields("metadata coverage", all_facts, ["year", "location_geo", "lab_or_author", "geo_scope"])

    checks = [
        (
            "nickel electrowinning",
            find_facts(material="никель", process="электроэкстракция"),
            5,
        ),
        (
            "leaching temperature 40-60",
            find_facts(process="выщелачивание", parameter="температура", value_min=40, value_max=60),
            5,
        ),
        (
            "mine waters",
            find_facts(material="шахтные воды"),
            5,
        ),
        (
            "PGM search",
            free_search("МПГ"),
            3,
        ),
        (
            "English electrowinning synonym",
            free_search("electrowinning"),
            5,
        ),
        (
            "year filter 2020-2025",
            find_facts(year_min=2020, year_max=2025),
            5,
        ),
        (
            "geo filter Russia",
            find_facts(geo="Россия"),
            5,
        ),
        (
            "geo scope domestic",
            find_facts(geo_scope="domestic"),
            5,
        ),
        (
            "geo scope foreign",
            find_facts(geo_scope="foreign"),
            5,
        ),
    ]

    for name, facts, min_count in checks:
        facts = require_results(name, facts, min_count=min_count)
        require_fact_fields(name, facts, ["source_file", "confidence"])
        print_examples(facts)

    invalid_search = free_search("???")
    if invalid_search:
        raise AssertionError(f"invalid punctuation search returned {len(invalid_search)} facts")

    invalid_filter = find_facts(material="???")
    if invalid_filter:
        raise AssertionError(f"invalid material filter returned {len(invalid_filter)} facts")

    print("OK: query smoke tests passed")


if __name__ == "__main__":
    main()
