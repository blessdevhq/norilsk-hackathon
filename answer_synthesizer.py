from collections import Counter, defaultdict


CONFIDENCE_SCORE = {
    "high": 3,
    "medium": 2,
    "low": 1,
}


def clean_text(value):
    return str(value or "").strip()


def normalized(value):
    return clean_text(value).lower()


def has_value(value):
    return clean_text(value) != ""


def has_digit(value):
    return any(char.isdigit() for char in clean_text(value))


def value_with_unit(fact):
    value = fact.get("result_value")
    unit = fact.get("result_unit")
    if not has_value(value):
        return ""

    value_text = clean_text(value)
    if has_value(unit) and normalized(unit) not in normalized(value_text):
        return f"{value_text} {clean_text(unit)}"
    return value_text


def fact_result_text(fact):
    prop = clean_text(fact.get("result_property")) or "результат"
    value = value_with_unit(fact)
    return f"{prop}: {value}" if value else prop


def confidence_score(fact):
    return CONFIDENCE_SCORE.get(normalized(fact.get("confidence")), 0)


def fact_quality_score(fact):
    score = confidence_score(fact) * 100
    if has_value(fact.get("source_quote")):
        score += 35
    if has_value(fact.get("year")):
        score += 10
    if has_value(fact.get("location_geo")):
        score += 10
    if has_value(fact.get("lab_or_author")):
        score += 10
    if has_digit(fact.get("result_value")):
        score += 8
    if fact.get("conditions"):
        score += 6
    return score


def fact_identity(fact):
    return (
        normalized(fact.get("material")),
        normalized(fact.get("process")),
        normalized(fact.get("result_property")),
        normalized(fact.get("result_value")),
        normalized(fact.get("result_unit")),
        clean_text(fact.get("source_file")),
        clean_text(fact.get("source_quote")),
    )


def rank_facts(facts):
    unique = []
    seen = set()
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        key = fact_identity(fact)
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)

    return sorted(
        unique,
        key=lambda fact: (
            -fact_quality_score(fact),
            clean_text(fact.get("source_file")),
            clean_text(fact.get("material")),
            clean_text(fact.get("process")),
            clean_text(fact.get("result_property")),
        ),
    )


def document_count(facts):
    return len({fact.get("source_file") for fact in facts if has_value(fact.get("source_file"))})


def sorted_years(facts):
    years = []
    for fact in facts:
        year = fact.get("year")
        if isinstance(year, int):
            years.append(year)
            continue
        text = clean_text(year)
        if text.isdigit():
            years.append(int(text))
    return sorted(set(years))


def top_counter_rows(facts, field, limit=8):
    counter = Counter(clean_text(fact.get(field)) for fact in facts if has_value(fact.get(field)))
    return [{"name": name, "facts": count} for name, count in counter.most_common(limit)]


def top_sources(facts, limit=8):
    counter = Counter(clean_text(fact.get("source_file")) for fact in facts if has_value(fact.get("source_file")))
    return [{"source_file": source, "facts": count} for source, count in counter.most_common(limit)]


def condition_text(fact, limit=4):
    conditions = fact.get("conditions")
    if not isinstance(conditions, list):
        return ""

    parts = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        parameter = clean_text(condition.get("parameter"))
        value = clean_text(condition.get("value"))
        unit = clean_text(condition.get("unit"))
        if not parameter and not value:
            continue
        if unit and unit.lower() not in value.lower():
            value = f"{value} {unit}".strip()
        parts.append(f"{parameter}: {value}".strip(": "))
        if len(parts) >= limit:
            break
    return "; ".join(parts)


def build_evidence_rows(facts, limit=50):
    ranked = rank_facts(facts)
    selected = []
    used_sources = set()

    for fact in ranked:
        source = clean_text(fact.get("source_file"))
        if source and source in used_sources:
            continue
        selected.append(fact)
        if source:
            used_sources.add(source)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        selected_ids = {id(fact) for fact in selected}
        for fact in ranked:
            if id(fact) in selected_ids:
                continue
            selected.append(fact)
            if len(selected) >= limit:
                break

    rows = []
    for fact in selected:
        rows.append(
            {
                "material": clean_text(fact.get("material")),
                "process": clean_text(fact.get("process")),
                "result": fact_result_text(fact),
                "conditions": condition_text(fact),
                "year": fact.get("year"),
                "location_geo": clean_text(fact.get("location_geo")),
                "lab_or_author": clean_text(fact.get("lab_or_author")),
                "source_file": clean_text(fact.get("source_file")),
                "source_quote": clean_text(fact.get("source_quote")),
                "confidence": clean_text(fact.get("confidence")) or "unknown",
            }
        )
    return rows


def build_methods(facts, limit=8):
    by_process = defaultdict(list)
    for fact in facts:
        process = clean_text(fact.get("process")) or "процесс не указан"
        by_process[process].append(fact)

    rows = []
    for process, group in by_process.items():
        ranked = rank_facts(group)
        materials = Counter(clean_text(fact.get("material")) for fact in group if has_value(fact.get("material")))
        properties = Counter(
            clean_text(fact.get("result_property")) for fact in group if has_value(fact.get("result_property"))
        )
        rows.append(
            {
                "process": process,
                "facts": len(group),
                "documents": document_count(group),
                "top_materials": ", ".join(name for name, _ in materials.most_common(3)),
                "top_results": ", ".join(name for name, _ in properties.most_common(3)),
                "representative_source": clean_text(ranked[0].get("source_file")) if ranked else "",
                "representative_quote": clean_text(ranked[0].get("source_quote")) if ranked else "",
                "_score": max((fact_quality_score(fact) for fact in group), default=0),
            }
        )

    rows.sort(key=lambda row: (-row["facts"], -row["_score"], row["process"]))
    for row in rows:
        row.pop("_score", None)
    return rows[:limit]


def build_experts(facts, limit=10):
    groups = defaultdict(list)
    for fact in facts:
        expert = clean_text(fact.get("lab_or_author"))
        if expert:
            groups[expert].append(fact)

    rows = []
    for expert, group in groups.items():
        rows.append(
            {
                "expert": expert,
                "facts": len(group),
                "documents": document_count(group),
                "top_sources": ", ".join(row["source_file"] for row in top_sources(group, limit=2)),
            }
        )
    rows.sort(key=lambda row: (-row["facts"], row["expert"]))
    return rows[:limit]


def build_geo_breakdown(facts, limit=10):
    groups = defaultdict(list)
    for fact in facts:
        geo = clean_text(fact.get("location_geo"))
        if geo:
            groups[geo].append(fact)

    rows = []
    for geo, group in groups.items():
        years = sorted_years(group)
        rows.append(
            {
                "location_geo": geo,
                "facts": len(group),
                "documents": document_count(group),
                "year_range": f"{years[0]}-{years[-1]}" if years else "",
            }
        )
    rows.sort(key=lambda row: (-row["facts"], row["location_geo"]))
    return rows[:limit]


def detect_potential_conflicts(facts):
    groups = defaultdict(list)
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        key = (
            normalized(fact.get("material")),
            normalized(fact.get("process")),
            normalized(fact.get("result_property")),
        )
        if not all(key):
            continue
        groups[key].append(fact)

    conflicts = []
    for (material, process, result_property), group in groups.items():
        values = sorted({clean_text(fact.get("result_value")) for fact in group if has_value(fact.get("result_value"))})
        directions = sorted({clean_text(fact.get("direction")) for fact in group if has_value(fact.get("direction"))})
        if len(values) <= 1 and len(directions) <= 1:
            continue

        ranked = rank_facts(group)
        conflicts.append(
            {
                "material": material,
                "process": process,
                "result_property": result_property,
                "values": values[:8],
                "directions": directions[:6],
                "facts": len(group),
                "sources": [row["source_file"] for row in top_sources(group, limit=4)],
                "status": "требует экспертной проверки",
                "example_quote": clean_text(ranked[0].get("source_quote")) if ranked else "",
            }
        )

    conflicts.sort(key=lambda row: (-row["facts"], row["material"], row["process"], row["result_property"]))
    return conflicts[:12]


def build_gaps(facts):
    total = len(facts or [])
    docs = document_count(facts)
    gaps = []

    if total == 0:
        return [
            {
                "gap": "По выбранному сценарию не найдено структурированных фактов.",
                "detail": "Нужно расширить корпус или ослабить фильтры.",
            }
        ]

    checks = [
        ("Мало независимых источников", docs < 3, f"найдено документов: {docs}"),
        (
            "Слабое покрытие годов",
            sum(1 for fact in facts if has_value(fact.get("year"))) < max(2, total // 5),
            "у значимой части фактов нет года",
        ),
        (
            "Слабое покрытие географии",
            sum(1 for fact in facts if has_value(fact.get("location_geo"))) < max(2, total // 5),
            "у значимой части фактов нет географической привязки",
        ),
        (
            "Слабое покрытие экспертов",
            sum(1 for fact in facts if has_value(fact.get("lab_or_author"))) < max(2, total // 5),
            "не всегда указан автор, организация или лаборатория",
        ),
        (
            "Недостаточно численных результатов",
            sum(1 for fact in facts if has_digit(fact.get("result_value"))) < max(2, total // 5),
            "мало фактов с численным значением результата",
        ),
        (
            "Недостаточно опорных цитат",
            sum(1 for fact in facts if has_value(fact.get("source_quote"))) < total,
            "часть фактов сложнее проверить вручную",
        ),
    ]

    for title, condition, detail in checks:
        if condition:
            gaps.append({"gap": title, "detail": detail})

    if not gaps:
        gaps.append(
            {
                "gap": "Критичных пробелов покрытия для демо-сценария не выявлено.",
                "detail": "Перед производственным применением всё равно нужна экспертная валидация.",
            }
        )
    return gaps


def build_limitations(facts):
    limitations = [
        "Ответ собран детерминированно из графа и не содержит live LLM-обобщений.",
        "Факты имеют статус auto_extracted и требуют экспертной проверки перед производственным использованием.",
        "Потенциальные противоречия являются сигналами для проверки, а не доказанными научными конфликтами.",
    ]
    if not facts:
        limitations.append("Для выбранного сценария нет фактов, поэтому вывод ограничен диагностикой пробела.")
    return limitations


def build_metrics(facts):
    years = sorted_years(facts)
    confidence = Counter(normalized(fact.get("confidence")) or "unknown" for fact in facts)
    return {
        "facts": len(facts),
        "documents": document_count(facts),
        "years": len(years),
        "year_range": f"{years[0]}-{years[-1]}" if years else "",
        "geographies": len({fact.get("location_geo") for fact in facts if has_value(fact.get("location_geo"))}),
        "experts": len({fact.get("lab_or_author") for fact in facts if has_value(fact.get("lab_or_author"))}),
        "high_confidence": confidence.get("high", 0),
        "medium_confidence": confidence.get("medium", 0),
        "low_confidence": confidence.get("low", 0),
        "unknown_confidence": confidence.get("unknown", 0),
        "top_sources": top_sources(facts, limit=6),
    }


def build_summary(title, facts, metrics, methods):
    if not facts:
        return (
            f"По сценарию «{title}» в текущем графе не найдено проверяемых фактов. "
            "Это следует показывать как пробел корпуса или повод ослабить фильтры."
        )

    method_names = [row["process"] for row in methods[:3] if row.get("process")]
    method_text = ", ".join(method_names) if method_names else "процессы не выделены"
    year_text = f" за период {metrics['year_range']}" if metrics.get("year_range") else ""
    geo_text = f", географий: {metrics['geographies']}" if metrics.get("geographies") else ""

    return (
        f"По сценарию «{title}» найдено {metrics['facts']} фактов из {metrics['documents']} документов"
        f"{year_text}{geo_text}. Наиболее представленные процессы: {method_text}. "
        "Ниже приведены только факты с трассировкой к источникам; вывод требует экспертной проверки."
    )


def markdown_escape(value):
    return clean_text(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(headers, rows):
    if not rows:
        return "Нет данных.\n"

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(markdown_escape(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines) + "\n"


def answer_to_markdown(answer):
    metrics = answer.get("metrics", {})
    lines = [
        f"# {answer.get('title', 'Аналитический ответ')}",
        "",
        "## Краткий вывод",
        answer.get("summary", ""),
        "",
        "## Что найдено",
        f"- Фактов: {metrics.get('facts', 0)}",
        f"- Документов: {metrics.get('documents', 0)}",
        f"- Диапазон годов: {metrics.get('year_range') or 'не указан'}",
        f"- Географий: {metrics.get('geographies', 0)}",
        f"- Экспертов / организаций: {metrics.get('experts', 0)}",
        f"- Confidence high/medium/low/unknown: {metrics.get('high_confidence', 0)}/"
        f"{metrics.get('medium_confidence', 0)}/{metrics.get('low_confidence', 0)}/"
        f"{metrics.get('unknown_confidence', 0)}",
        "",
        "## Методы и процессы",
        markdown_table(
            ["process", "facts", "documents", "top_materials", "top_results", "representative_source"],
            answer.get("methods", []),
        ),
        "## Доказательства",
        markdown_table(
            [
                "material",
                "process",
                "result",
                "conditions",
                "year",
                "location_geo",
                "source_file",
                "source_quote",
                "confidence",
            ],
            answer.get("evidence_rows", [])[:20],
        ),
        "## Эксперты / организации",
        markdown_table(["expert", "facts", "documents", "top_sources"], answer.get("experts", [])),
        "## География",
        markdown_table(["location_geo", "facts", "documents", "year_range"], answer.get("geo_breakdown", [])),
        "## Потенциальные противоречия",
    ]

    conflicts = answer.get("potential_conflicts", [])
    if conflicts:
        for conflict in conflicts:
            values = ", ".join(conflict.get("values") or [])
            directions = ", ".join(conflict.get("directions") or [])
            lines.append(
                "- "
                f"{conflict.get('material')} / {conflict.get('process')} / {conflict.get('result_property')}: "
                f"значения [{values or 'нет'}], направления [{directions or 'нет'}], "
                f"статус: {conflict.get('status')}"
            )
    else:
        lines.append("Потенциальные противоречия по выбранному набору фактов не выявлены.")

    lines.extend(["", "## Пробелы"])
    for gap in answer.get("gaps", []):
        lines.append(f"- {gap.get('gap')}: {gap.get('detail')}")

    lines.extend(["", "## Ограничения"])
    for limitation in answer.get("limitations", []):
        lines.append(f"- {limitation}")

    return "\n".join(lines).strip() + "\n"


def build_answer(title, facts):
    ranked = rank_facts(facts or [])
    metrics = build_metrics(ranked)
    methods = build_methods(ranked)
    answer = {
        "title": title,
        "summary": "",
        "metrics": metrics,
        "methods": methods,
        "evidence_rows": build_evidence_rows(ranked, limit=50),
        "experts": build_experts(ranked),
        "geo_breakdown": build_geo_breakdown(ranked),
        "year_range": metrics.get("year_range", ""),
        "potential_conflicts": detect_potential_conflicts(ranked),
        "gaps": build_gaps(ranked),
        "limitations": build_limitations(ranked),
    }
    answer["summary"] = build_summary(title, ranked, metrics, methods)
    answer["markdown"] = answer_to_markdown(answer)
    return answer
