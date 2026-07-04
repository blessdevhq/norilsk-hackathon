from answer_synthesizer import build_answer, detect_potential_conflicts
from app import DEMO_PRESETS, build_manual_submission, demo_preset_results, demo_preset_status


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
    require(len(DEMO_PRESETS) == 4, "expected exactly four TZ demo presets")

    for preset in DEMO_PRESETS:
        title = preset["label"]
        facts = demo_preset_results(title)
        status, detail = demo_preset_status(title, facts)
        require(status in {"найдено", "частично найдено", "пробел"}, f"{title}: invalid preset status")
        require(detail, f"{title}: preset status detail is empty")
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


def test_manual_submission_shape():
    row = build_manual_submission(
        expert_name="Гипроникель",
        material="шахтные воды",
        process="обратный осмос",
        result_property="извлечение воды",
        result_value="95",
        result_unit="%",
        condition_parameter="сульфаты",
        condition_value="200-300",
        condition_unit="мг/л",
        location_geo="Россия",
        source_quote="ручная проверка эксперта",
        comment="демо-заявка",
    )
    require(row["status"] == "needs_review", "manual submission should go to review")
    require(row["facts_count"] == 1, "manual submission should contain one fact")
    require(row["records"][0]["record_type"] == "fact", "manual record should be a fact")
    require(row["records"][0]["context"]["lab_or_author"] == "Гипроникель", "expert should be preserved")


def main():
    test_demo_answers()
    test_conflicts_tolerate_partial_facts()
    test_manual_submission_shape()
    print("OK: answer synthesizer tests passed")


if __name__ == "__main__":
    main()
