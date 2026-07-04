from answer_synthesizer import build_answer, detect_potential_conflicts
from app import DEMO_PRESETS, demo_preset_results


REQUIRED_KEYS = {
    "summary",
    "metrics",
    "methods",
    "evidence_rows",
    "experts",
    "geo_breakdown",
    "year_range",
    "potential_conflicts",
    "gaps",
    "limitations",
    "markdown",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def test_demo_answers():
    for preset in DEMO_PRESETS:
        title = preset["label"]
        facts = demo_preset_results(title)
        answer = build_answer(title, facts)

        missing_keys = REQUIRED_KEYS - set(answer)
        require(not missing_keys, f"{title}: missing answer keys {sorted(missing_keys)}")
        require(answer["summary"], f"{title}: empty summary")
        require(answer["markdown"], f"{title}: empty markdown")
        require("## Краткий вывод" in answer["markdown"], f"{title}: missing summary markdown section")
        require("## Доказательства" in answer["markdown"], f"{title}: missing evidence markdown section")
        require("## Ограничения" in answer["markdown"], f"{title}: missing limitations markdown section")

        if facts:
            rows = answer["evidence_rows"]
            require(rows, f"{title}: facts exist but evidence rows are empty")
            require(any(row.get("source_file") for row in rows), f"{title}: evidence rows have no source_file")
            require(any(row.get("confidence") for row in rows), f"{title}: evidence rows have no confidence")
            if any(fact.get("source_quote") for fact in facts):
                require(any(row.get("source_quote") for row in rows), f"{title}: source quotes were not preserved")

        print(
            f"{title}: facts={answer['metrics']['facts']}, "
            f"docs={answer['metrics']['documents']}, evidence={len(answer['evidence_rows'])}"
        )


def test_conflicts_tolerate_partial_facts():
    partial_facts = [
        {
            "material": "раствор",
            "process": "очистка",
            "result_property": "содержание сульфатов",
            "result_value": "200",
            "result_unit": "мг/л",
            "confidence": "high",
            "source_file": "source_a.txt",
        },
        {
            "material": "раствор",
            "process": "очистка",
            "result_property": "содержание сульфатов",
            "result_value": "300",
            "result_unit": "мг/л",
            "confidence": "medium",
            "source_file": "source_b.txt",
        },
        {
            "material": None,
            "process": "очистка",
            "result_property": "содержание сульфатов",
            "result_value": None,
        },
    ]

    conflicts = detect_potential_conflicts(partial_facts)
    require(conflicts, "expected conflict for different result values")

    empty_answer = build_answer("empty", [])
    require(empty_answer["gaps"], "empty answer should explain the gap")
    require(empty_answer["markdown"], "empty answer should still export markdown")


def main():
    test_demo_answers()
    test_conflicts_tolerate_partial_facts()
    print("OK: answer synthesizer tests passed")


if __name__ == "__main__":
    main()
