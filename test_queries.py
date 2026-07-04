from query_graph import find_facts, free_search, load_graph


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


def main():
    graph = load_graph()
    if graph is None:
        raise AssertionError("graph.json was not loaded")

    all_facts = require_results("all facts", find_facts(), min_count=100)
    require_fact_fields("all facts", all_facts, ["source_file", "confidence"])
    require_fact_fields("metadata coverage", all_facts, ["year", "location_geo", "lab_or_author"])

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
