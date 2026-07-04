import html
import json
from collections import Counter
from pathlib import Path

import streamlit as st

from answer_synthesizer import build_answer
from gap_matrix import build_matrix, gaps, render
from query_graph import find_facts, free_search, neighbors


GRAPH_PATH = Path("graph.json")
CARD_LIMIT = 40
DEMO_SOURCE_DOC_COUNT = 25
PREPARED_TXT_COUNT = 152

DEMO_PRESETS = [
    {
        "label": "Электроэкстракция никеля",
        "description": "Параметры, источники, цитаты, confidence и география по никелевым электролитам.",
        "kind": "facts",
        "material": "никель",
        "process": "электроэкстракция",
    },
    {
        "label": "Шахтные воды и очистка",
        "description": "Методы обработки, условия, результаты и готовый аналитический отчет.",
        "kind": "facts",
        "material": "шахтные воды",
    },
    {
        "label": "МПГ, штейн и шлак",
        "description": "Междисциплинарный поиск по МПГ, штейнам, шлакам и переделам.",
        "kind": "search",
        "query": "МПГ",
    },
    {
        "label": "Выщелачивание 40-60 C",
        "description": "Числовой срез условий: температура, процесс и результат в одной карточке факта.",
        "kind": "facts",
        "process": "выщелачивание",
        "parameter": "температура",
        "value_min": 40,
        "value_max": 60,
    },
]

MATRIX_AXIS_LABELS = {
    "material": "Материалы",
    "process": "Процессы",
    "property": "Показатели",
}

RELATION_COLUMNS = {
    "entity": "Сущность",
    "entity_type": "Тип",
    "related_entity": "Связанная сущность",
    "related_type": "Тип связи",
    "direction": "Направление",
    "edge_type": "Отношение",
    "process": "Процесс",
    "source_file": "Источник",
    "source_quote": "Цитата",
    "year": "Год",
    "location_geo": "География",
    "lab_or_author": "Эксперт / организация",
    "confidence": "Confidence",
    "value": "Значение",
    "unit": "Ед.",
}

EVIDENCE_COLUMNS = {
    "material": "Материал",
    "process": "Процесс",
    "result": "Результат",
    "conditions": "Условия",
    "year": "Год",
    "location_geo": "География",
    "lab_or_author": "Эксперт / организация",
    "source_file": "Источник",
    "source_quote": "Цитата",
    "confidence": "Confidence",
}


def graph_mtime():
    try:
        return GRAPH_PATH.stat().st_mtime
    except Exception:
        return 0


def top_entities(nodes, node_type, limit=6):
    rows = []
    for node in nodes:
        if node.get("node_type") != node_type:
            continue
        name = node.get("display_name") or node.get("name") or node.get("base") or node.get("id")
        try:
            mentions = int(node.get("mention_count") or 0)
        except Exception:
            mentions = 0
        rows.append({"name": name, "mentions": mentions})

    rows.sort(key=lambda item: (-item["mentions"], str(item["name"])))
    return rows[:limit]


@st.cache_data(show_spinner=False)
def load_graph_stats(graph_mtime_value):
    try:
        data = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Не удалось прочитать graph.json: {exc}"}

    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))
    yields_edges = [edge for edge in links if edge.get("edge_type") == "yields"]
    confidence_counts = Counter(str(edge.get("confidence") or "unknown").lower() for edge in yields_edges)
    graph_meta = data.get("graph", {})

    def has_digit(value):
        return any(char.isdigit() for char in str(value or ""))

    return {
        "nodes": len(nodes),
        "links": len(links),
        "documents": sum(1 for node in nodes if node.get("node_type") == "Document"),
        "facts": len(yields_edges),
        "materials": sum(1 for node in nodes if node.get("node_type") == "Material"),
        "processes": sum(1 for node in nodes if node.get("node_type") == "Process"),
        "properties": sum(1 for node in nodes if node.get("node_type") == "Property"),
        "experts": sum(1 for edge in yields_edges if edge.get("lab_or_author")),
        "with_year": sum(1 for edge in yields_edges if edge.get("year") is not None),
        "with_geo": sum(1 for edge in yields_edges if edge.get("location_geo")),
        "with_expert": sum(1 for edge in yields_edges if edge.get("lab_or_author")),
        "with_conditions": sum(1 for edge in yields_edges if edge.get("conditions")),
        "with_numeric_result": sum(1 for edge in yields_edges if has_digit(edge.get("value"))),
        "updated_at": graph_meta.get("updated_at"),
        "verification_status": graph_meta.get("verification_status"),
        "confidence_counts": dict(confidence_counts),
        "top_materials": top_entities(nodes, "Material"),
        "top_processes": top_entities(nodes, "Process"),
        "top_properties": top_entities(nodes, "Property"),
        "error": None,
    }


@st.cache_data(show_spinner=False)
def cached_matrix(axis1, axis2, condition_parameter, top1, top2, min_mentions, graph_mtime_value):
    return build_matrix(
        axis1=axis1,
        axis2=axis2,
        condition_parameter=condition_parameter,
        top_n_axis1=top1,
        top_n_axis2=top2,
        min_mentions=min_mentions,
    )


def optional_float(value):
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        st.warning(f"Не удалось прочитать число: {value}")
        return None


def fact_key(fact):
    return (
        fact.get("material"),
        fact.get("process"),
        fact.get("result_property"),
        fact.get("result_value"),
        fact.get("result_unit"),
        fact.get("source_file"),
        fact.get("source_quote"),
    )


def merge_results(*groups):
    seen = set()
    merged = []
    for group in groups:
        for fact in group or []:
            key = fact_key(fact)
            if key in seen:
                continue
            seen.add(key)
            merged.append(fact)
    return merged


def demo_preset_results(label):
    preset = next((item for item in DEMO_PRESETS if item["label"] == label), None)
    if not preset:
        return []

    kind = preset.get("kind")
    if kind == "search":
        query = preset["query"]
        return merge_results(free_search(query), find_facts(material=query))

    if kind == "facts":
        return find_facts(
            material=preset.get("material"),
            process=preset.get("process"),
            property_query=preset.get("property_query"),
            parameter=preset.get("parameter"),
            value_min=preset.get("value_min"),
            value_max=preset.get("value_max"),
            unit=preset.get("unit"),
            result_value_min=preset.get("result_value_min"),
            result_value_max=preset.get("result_value_max"),
            result_unit=preset.get("result_unit"),
            year_min=preset.get("year_min"),
            year_max=preset.get("year_max"),
            geo=preset.get("geo"),
            expert=preset.get("expert"),
            confidence=preset.get("confidence"),
        )

    return []


def clean_display(value, fallback="не указано"):
    text = str(value or "").strip()
    return text if text else fallback


def compact_text(value, max_len=120):
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def value_with_unit(fact):
    value = fact.get("result_value")
    unit = fact.get("result_unit")
    if value is None:
        return ""

    value_text = str(value)
    if unit and str(unit).lower() not in value_text.lower():
        return f"{value_text} {unit}"
    return value_text


def fact_result_text(fact):
    prop = clean_display(fact.get("result_property"), fallback="результат")
    value = value_with_unit(fact)
    return f"{prop}: {value}" if value else prop


def format_conditions(fact):
    conditions = fact.get("conditions")
    if not isinstance(conditions, list):
        return []

    rows = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        parameter = condition.get("parameter")
        value = condition.get("value")
        unit = condition.get("unit")
        if not parameter and value is None:
            continue
        value_text = "" if value is None else str(value)
        if unit and str(unit).lower() not in value_text.lower():
            value_text = f"{value_text} {unit}".strip()
        rows.append((clean_display(parameter, fallback="условие"), value_text or "не указано"))
    return rows


def confidence_badge(confidence):
    value = str(confidence or "unknown").lower()
    labels = {"high": "high", "medium": "medium", "low": "low"}
    css_class = labels.get(value, "unknown")
    return f'<span class="confidence {css_class}">{html.escape(value)}</span>'


def summarize_results(results):
    docs = {fact.get("source_file") for fact in results if fact.get("source_file")}
    years = {fact.get("year") for fact in results if fact.get("year") not in (None, "")}
    geos = {fact.get("location_geo") for fact in results if fact.get("location_geo")}
    confidence = Counter(str(fact.get("confidence") or "unknown").lower() for fact in results)
    return {
        "facts": len(results),
        "documents": len(docs),
        "years": len(years),
        "geos": len(geos),
        "confidence": confidence,
    }


def render_metric(label, value, note=None):
    note_html = f'<div class="metric-note">{html.escape(str(note))}</div>' if note else ""
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-label">{html.escape(str(label))}</div>
          <div class="metric-value">{html.escape(str(value))}</div>
          {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_result_summary(results):
    summary = summarize_results(results)
    cols = st.columns(4)
    cols[0].metric("Факты", summary["facts"])
    cols[1].metric("Документы", summary["documents"])
    cols[2].metric("Годы", summary["years"])
    cols[3].metric("Географии", summary["geos"])

    confidence = summary["confidence"]
    st.caption(
        "Confidence: "
        f"high {confidence.get('high', 0)} | "
        f"medium {confidence.get('medium', 0)} | "
        f"low {confidence.get('low', 0)} | "
        f"unknown {confidence.get('unknown', 0)}"
    )


def render_fact_row(fact, index=0):
    material = clean_display(fact.get("material"), fallback="материал не указан")
    process = clean_display(fact.get("process"), fallback="процесс не указан")
    result = fact_result_text(fact)
    header = f"{material} -> {process} -> {result}"

    with st.expander(header, expanded=index < 3):
        meta = [
            ("Источник", fact.get("source_file")),
            ("Год", fact.get("year")),
            ("География", fact.get("location_geo")),
            ("Эксперт / организация", fact.get("lab_or_author")),
            ("Оборудование", fact.get("equipment")),
            ("Chunk", fact.get("chunk_id")),
        ]
        meta_items = []
        for label, value in meta:
            if value not in (None, ""):
                meta_items.append(
                    f"<div><span>{html.escape(label)}</span><strong>{html.escape(compact_text(value, 160))}</strong></div>"
                )

        st.markdown(
            f"""
            <div class="fact-detail">
              <div class="fact-badges">{confidence_badge(fact.get("confidence"))}</div>
              <div class="fact-meta-grid">{''.join(meta_items)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        conditions = format_conditions(fact)
        if conditions:
            condition_html = "".join(
                f"<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td></tr>"
                for label, value in conditions[:8]
            )
            st.markdown(
                f"""
                <div class="detail-heading">Условия</div>
                <table class="condition-table">{condition_html}</table>
                """,
                unsafe_allow_html=True,
            )

        quote = fact.get("source_quote")
        if quote:
            st.markdown(
                f"""
                <div class="detail-heading">Опорная цитата</div>
                <div class="quote-box">{html.escape(str(quote))}</div>
                """,
                unsafe_allow_html=True,
            )


def show_fact_results(title, results, limit=CARD_LIMIT):
    st.markdown(f"### {title}")
    if not results:
        st.info("Ничего не найдено. Попробуйте ослабить фильтры или выбрать демо-сценарий.")
        return

    render_result_summary(results)
    st.caption(f"Показано {min(len(results), limit)} из {len(results)}")
    for index, fact in enumerate(results[:limit]):
        render_fact_row(fact, index=index)


def relation_table(rows):
    useful_columns = list(RELATION_COLUMNS)
    table_rows = []
    for row in rows:
        table_rows.append(
            {
                RELATION_COLUMNS[column]: row.get(column)
                for column in useful_columns
            }
        )
    return table_rows


def render_sidebar(stats):
    with st.sidebar:
        st.markdown("### Научный клубок")
        st.caption("R&D memory system: факты, источники, эксперты и пробелы исследований.")
        st.divider()
        st.metric("Документы", stats.get("documents", 0))
        st.metric("Факты", stats.get("facts", 0))
        st.caption(f"Демо: {DEMO_SOURCE_DOC_COUNT} документов. Ingest подготовил {PREPARED_TXT_COUNT} txt.")
        status = stats.get("verification_status") or "auto_extracted"
        status_label = "автоизвлечение" if str(status) == "auto_extracted" else str(status)
        st.markdown(
            f"""
            <div class="sidebar-status">
              <div class="sidebar-status-label">Статус</div>
              <div class="sidebar-status-value">{html.escape(status_label)}</div>
              <div class="sidebar-status-note">требует экспертной проверки</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("MVP: факты извлечены автоматически и требуют экспертной проверки перед производственным применением.")


def render_page_header(stats):
    st.markdown(
        """
        <div class="page-kicker">R&D memory system</div>
        <h1>Научный клубок: карта знаний R&D</h1>
        <p class="page-lead">
          Система сохраняет институциональную память исследований: что уже пробовали,
          где источники, какие выводы подтверждены, кто владеет экспертизой и где
          остаются пробелы. Каждый ответ опирается на документ, цитату и структурированный факт.
        </p>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(4)
    with cols[0]:
        render_metric("Документы", stats.get("documents", 0), f"демо; {PREPARED_TXT_COUNT} txt готово")
    with cols[1]:
        render_metric("Факты", stats.get("facts", 0), "структурированные связи")
    with cols[2]:
        render_metric("Узлы / связи", f"{stats.get('nodes', 0)} / {stats.get('links', 0)}", "граф знаний")
    with cols[3]:
        render_metric("С условиями", stats.get("with_conditions", 0), "параметры процессов")


def render_scenario_picker(prefix, default_label=None):
    if default_label is None:
        default_label = DEMO_PRESETS[0]["label"]

    state_key = f"{prefix}_selected_preset"
    if state_key not in st.session_state:
        st.session_state[state_key] = default_label

    cols = st.columns(len(DEMO_PRESETS))
    for index, preset in enumerate(DEMO_PRESETS):
        with cols[index]:
            active = st.session_state[state_key] == preset["label"]
            button_label = preset["label"]
            if st.button(button_label, key=f"{prefix}_preset_{index}", use_container_width=True):
                st.session_state[state_key] = preset["label"]
                active = True
            css_class = "scenario-note active" if active else "scenario-note"
            st.markdown(
                f'<div class="{css_class}">{html.escape(preset["description"])}</div>',
                unsafe_allow_html=True,
            )

    return st.session_state[state_key]


def render_overview_tab(stats):
    st.markdown("### Демо-пульт")
    st.caption("Четыре сценария из логики ТЗ: проверяемый ответ, междисциплинарный поиск и пробелы R&D.")
    selected = render_scenario_picker("overview")
    results = demo_preset_results(selected)
    show_fact_results(selected, results, limit=8)

    st.markdown("### Почему это не RAG-чат")
    cols = st.columns(4)
    with cols[0]:
        st.markdown(
            """
            <div class="evidence-panel">
              <strong>Проверяемость</strong>
              <p>Каждый факт связан с документом, chunk, цитатой и confidence.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            """
            <div class="evidence-panel">
              <strong>Структурный граф</strong>
              <p>Документы превращаются в сущности и связи: материал, процесс, условия, результат.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            """
            <div class="evidence-panel">
              <strong>Параметрический поиск</strong>
              <p>Фильтры работают по материалу, процессу, числам, году, географии и экспертам.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            """
            <div class="evidence-panel">
              <strong>Пробелы R&D</strong>
              <p>Матрица показывает не только что известно, но и какие связки слабо изучены.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def localized_rows(rows, column_map):
    table_rows = []
    for row in rows or []:
        table_rows.append({label: row.get(key) for key, label in column_map.items()})
    return table_rows


def answer_file_name(title):
    safe = "".join(char if char.isalnum() else "_" for char in str(title).lower())
    safe = "_".join(part for part in safe.split("_") if part)
    return f"scientific_answer_{safe or 'report'}.md"


def render_answer_metrics(answer):
    metrics = answer.get("metrics", {})
    cols = st.columns(5)
    cols[0].metric("Факты", metrics.get("facts", 0))
    cols[1].metric("Документы", metrics.get("documents", 0))
    cols[2].metric("Период", metrics.get("year_range") or "нет")
    cols[3].metric("Географии", metrics.get("geographies", 0))
    cols[4].metric("Эксперты", metrics.get("experts", 0))

    st.caption(
        "Confidence high/medium/low/unknown: "
        f"{metrics.get('high_confidence', 0)} / "
        f"{metrics.get('medium_confidence', 0)} / "
        f"{metrics.get('low_confidence', 0)} / "
        f"{metrics.get('unknown_confidence', 0)}"
    )


def render_conflicts(conflicts):
    if not conflicts:
        st.caption("Потенциальные противоречия по выбранному набору фактов не выявлены.")
        return

    rows = []
    for conflict in conflicts:
        rows.append(
            {
                "Материал": conflict.get("material"),
                "Процесс": conflict.get("process"),
                "Показатель": conflict.get("result_property"),
                "Значения": ", ".join(conflict.get("values") or []),
                "Направления": ", ".join(conflict.get("directions") or []),
                "Факты": conflict.get("facts"),
                "Источники": ", ".join(conflict.get("sources") or []),
                "Статус": conflict.get("status"),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_answer_tab():
    st.markdown("### Аналитический ответ")
    st.caption(
        "Детерминированный mini-review: все выводы собраны только из фактов графа, "
        "без live LLM и без утверждений без источника."
    )

    selected = render_scenario_picker("answer")
    facts = demo_preset_results(selected)
    answer = build_answer(selected, facts)

    render_answer_metrics(answer)
    st.markdown(
        f"""
        <div class="answer-summary">
          <strong>Краткий вывод</strong>
          <p>{html.escape(answer.get("summary", ""))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.download_button(
        "Скачать Markdown-отчет",
        data=answer.get("markdown", "").encode("utf-8"),
        file_name=answer_file_name(selected),
        mime="text/markdown",
        use_container_width=True,
    )

    st.markdown("### Что найдено")
    methods = answer.get("methods", [])
    if methods:
        st.dataframe(
            localized_rows(
                methods,
                {
                    "process": "Процесс",
                    "facts": "Факты",
                    "documents": "Документы",
                    "top_materials": "Материалы",
                    "top_results": "Показатели",
                    "representative_source": "Источник",
                    "representative_quote": "Опорная цитата",
                },
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Методы не выделены для выбранного сценария.")

    st.markdown("### Таблица доказательств")
    evidence_rows = answer.get("evidence_rows", [])
    if evidence_rows:
        st.dataframe(localized_rows(evidence_rows, EVIDENCE_COLUMNS), use_container_width=True, hide_index=True)
    else:
        st.caption("Доказательства отсутствуют.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Эксперты / организации")
        experts = answer.get("experts", [])
        if experts:
            st.dataframe(
                localized_rows(
                    experts,
                    {
                        "expert": "Эксперт / организация",
                        "facts": "Факты",
                        "documents": "Документы",
                        "top_sources": "Источники",
                    },
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Эксперты или организации в фактах не указаны.")

    with col2:
        st.markdown("### География")
        geos = answer.get("geo_breakdown", [])
        if geos:
            st.dataframe(
                localized_rows(
                    geos,
                    {
                        "location_geo": "География",
                        "facts": "Факты",
                        "documents": "Документы",
                        "year_range": "Период",
                    },
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("География в фактах не указана.")

    st.markdown("### Потенциальные противоречия")
    st.caption("Это сигналы для экспертной проверки, а не доказанные научные конфликты.")
    render_conflicts(answer.get("potential_conflicts", []))

    st.markdown("### Пробелы")
    for gap in answer.get("gaps", []):
        st.markdown(
            f"""
            <div class="gap-row">
              <strong>{html.escape(str(gap.get("gap", "")))}</strong>
              <div class="gap-detail">{html.escape(str(gap.get("detail", "")))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("### Ограничения")
    for limitation in answer.get("limitations", []):
        st.markdown(f"- {limitation}")


def filters_have_values(values):
    return any(str(value or "").strip() for value in values)


def collect_filter_kwargs(prefix):
    with st.expander("Расширенные фильтры", expanded=False):
        col1, col2, col3 = st.columns(3)
        filter_material = col1.text_input("Материал", key=f"{prefix}_material")
        filter_process = col2.text_input("Процесс", key=f"{prefix}_process")
        filter_property = col3.text_input("Показатель", key=f"{prefix}_property", placeholder="извлечение")

        col4, col5, col6 = st.columns(3)
        filter_parameter = col4.text_input("Параметр условия", key=f"{prefix}_parameter", placeholder="температура")
        value_min_text = col5.text_input("Значение от", key=f"{prefix}_value_min", placeholder="40")
        value_max_text = col6.text_input("Значение до", key=f"{prefix}_value_max", placeholder="60")

        col7, col8, col9 = st.columns(3)
        year_min_text = col7.text_input("Год от", key=f"{prefix}_year_min", placeholder="2020")
        year_max_text = col8.text_input("Год до", key=f"{prefix}_year_max", placeholder="2025")
        filter_geo = col9.text_input("География", key=f"{prefix}_geo", placeholder="Россия")

        col10, col11 = st.columns(2)
        filter_expert = col10.text_input("Эксперт / организация", key=f"{prefix}_expert", placeholder="Гипроникель")
        confidence_choice = col11.selectbox(
            "Confidence",
            ["", "high", "medium", "low"],
            format_func=lambda value: value or "любой",
            key=f"{prefix}_confidence",
        )

    values = [
        filter_material,
        filter_process,
        filter_property,
        filter_parameter,
        value_min_text,
        value_max_text,
        year_min_text,
        year_max_text,
        filter_geo,
        filter_expert,
        confidence_choice,
    ]

    return filters_have_values(values), {
        "material": filter_material.strip() or None,
        "process": filter_process.strip() or None,
        "property_query": filter_property.strip() or None,
        "parameter": filter_parameter.strip() or None,
        "value_min": optional_float(value_min_text),
        "value_max": optional_float(value_max_text),
        "year_min": optional_float(year_min_text),
        "year_max": optional_float(year_max_text),
        "geo": filter_geo.strip() or None,
        "expert": filter_expert.strip() or None,
        "confidence": confidence_choice or None,
    }


def render_search_tab():
    st.markdown("### Поиск по графу")
    st.caption("Введите тему или используйте фильтры. Результаты показывают только факты с источником.")
    query = st.text_input(
        "Запрос",
        placeholder="Например: никель, шахтные воды, электроэкстракция, МПГ",
        key="search_query_main",
    )

    filters_used, filter_kwargs = collect_filter_kwargs("search")

    results = []
    if query.strip():
        results = merge_results(free_search(query.strip()), find_facts(material=query.strip()))
    if filters_used:
        filtered = find_facts(**filter_kwargs)
        results = merge_results(results, filtered) if results else filtered

    if query.strip() or filters_used:
        show_fact_results("Результаты", results)
    else:
        selected = render_scenario_picker("search", default_label=DEMO_PRESETS[1]["label"])
        show_fact_results(selected, demo_preset_results(selected), limit=6)


def render_gap_candidate(gap, axis1_label, axis2_label):
    left = clean_display(gap.get(axis1_label), fallback="ось 1")
    right = clean_display(gap.get(axis2_label), fallback="ось 2")
    axis1_total = gap.get("axis1_total", 0)
    axis2_total = gap.get("axis2_total", 0)
    interest = gap.get("interest", 0)
    st.markdown(
        f"""
        <div class="gap-row">
          <strong>{html.escape(str(left))}</strong> x <strong>{html.escape(str(right))}</strong>
          <div class="gap-detail">темы часто встречаются отдельно: {axis1_total} и {axis2_total}; приоритет {interest}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_gap_tab(mtime):
    st.markdown("### Матрица пробелов")
    st.caption(
        "Центральная фича MVP: система не только отвечает, но и показывает слабопокрытые R&D-комбинации."
    )

    axis_options = ["material", "process", "property"]
    control_cols = st.columns([1, 1, 1.1, 0.8, 0.8])
    axis1 = control_cols[0].selectbox(
        "Строки",
        axis_options,
        index=0,
        format_func=lambda value: MATRIX_AXIS_LABELS.get(value, value),
        key="gap_axis1",
    )
    axis2 = control_cols[1].selectbox(
        "Столбцы",
        axis_options,
        index=1,
        format_func=lambda value: MATRIX_AXIS_LABELS.get(value, value),
        key="gap_axis2",
    )
    condition_choice = control_cols[2].selectbox(
        "Числовое условие",
        ["", "температура", "давление", "концентрация"],
        format_func=lambda value: value or "нет",
        index=0,
        key="gap_condition",
    )
    top1 = control_cols[3].slider("Строк", 8, 24, 15, key="gap_top1")
    top2 = control_cols[4].slider("Столбцов", 6, 18, 10, key="gap_top2")
    condition_parameter = condition_choice or None

    try:
        df = cached_matrix(axis1, axis2, condition_parameter, top1, top2, 3, mtime)
        fig = render(df)
        if fig is None:
            st.warning("Матрица построена, но Plotly недоступен для отрисовки.")
        else:
            st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        df = None
        st.error(f"Ошибка построения матрицы: {exc}")

    st.markdown("### Кандидаты на исследование")
    if df is None:
        st.caption("Матрица недоступна.")
        return

    try:
        axis1_label = df.attrs.get("axis1", axis1)
        axis2_label = df.attrs.get("axis2", axis2)
        gap_rows = gaps(df)[:8]
        if not gap_rows:
            st.caption("Пробелы не найдены для текущих осей.")
            return
        for gap in gap_rows:
            render_gap_candidate(gap, axis1_label, axis2_label)
    except Exception as exc:
        st.error(f"Ошибка расчета пробелов: {exc}")


def render_relations_tab():
    st.markdown("### Связи сущности")
    st.caption("Диагностический режим: покажите все входящие и исходящие связи материала, процесса или показателя.")
    entity_name = st.text_input("Имя сущности", placeholder="Например: выщелачивание", key="relations_entity")
    if not entity_name.strip():
        st.info("Введите название сущности, чтобы увидеть связанные материалы, процессы, документы и показатели.")
        return

    try:
        rows = neighbors(entity_name.strip())
        if rows:
            st.dataframe(relation_table(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("Связи не найдены.")
    except Exception as exc:
        st.error(f"Ошибка поиска связей: {exc}")


def render_quality_tab(stats):
    st.markdown("### Качество данных")
    st.caption("Этот экран показывает покрытие корпуса и ограничения MVP. Он нужен для честной демонстрации статуса данных.")

    coverage_cols = st.columns(5)
    coverage_cols[0].metric("С годом", stats.get("with_year", 0))
    coverage_cols[1].metric("С географией", stats.get("with_geo", 0))
    coverage_cols[2].metric("С экспертами", stats.get("with_expert", 0))
    coverage_cols[3].metric("С условиями", stats.get("with_conditions", 0))
    coverage_cols[4].metric("С числами", stats.get("with_numeric_result", 0))

    confidence_counts = stats.get("confidence_counts", {})
    confidence_cols = st.columns(4)
    confidence_cols[0].metric("High", confidence_counts.get("high", 0))
    confidence_cols[1].metric("Medium", confidence_counts.get("medium", 0))
    confidence_cols[2].metric("Low", confidence_counts.get("low", 0))
    confidence_cols[3].metric("Unknown", confidence_counts.get("unknown", 0))

    st.markdown(
        f"""
        <div class="verification-box">
          <strong>Статус графа:</strong> {html.escape(str(stats.get("verification_status") or "auto_extracted"))}<br>
          <strong>Дата сборки:</strong> {html.escape(str(stats.get("updated_at") or "не указано"))}<br>
          <strong>Ограничение:</strong> факты извлечены автоматически и требуют экспертной проверки перед производственным использованием.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    for title, rows, column in [
        ("Топ материалов", stats.get("top_materials", []), col1),
        ("Топ процессов", stats.get("top_processes", []), col2),
        ("Топ показателей", stats.get("top_properties", []), col3),
    ]:
        with column:
            st.markdown(f"#### {title}")
            if rows:
                for item in rows:
                    st.markdown(
                        f'<div class="entity-row"><span>{html.escape(str(item["name"]))}</span><strong>{item["mentions"]}</strong></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Нет данных.")


def css():
    st.markdown(
        """
        <style>
          :root {
            --bg: #0d1117;
            --panel: #151922;
            --panel-soft: #11161f;
            --border: #2b313c;
            --text: #eef2f7;
            --muted: #9aa4b2;
            --subtle: #687386;
            --accent: #67c1b5;
            --accent-2: #c7b36a;
            --danger: #d37b7b;
          }
          .stApp {
            background: var(--bg);
            color: var(--text);
          }
          .block-container {
            padding-top: 1.8rem;
            padding-bottom: 3rem;
            max-width: 1280px;
          }
          h1, h2, h3, h4 {
            letter-spacing: 0;
          }
          h1 {
            margin-bottom: 0.25rem;
            font-size: 2rem;
            line-height: 1.15;
          }
          .page-kicker {
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.35rem;
          }
          .page-lead {
            color: var(--muted);
            max-width: 860px;
            font-size: 1rem;
            line-height: 1.55;
            margin: 0.25rem 0 1rem;
          }
          .metric-card,
          .evidence-panel {
            border: 1px solid var(--border);
            background: var(--panel);
            border-radius: 8px;
            padding: 0.9rem 1rem;
            min-height: 92px;
          }
          .metric-label {
            color: var(--muted);
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }
          .metric-value {
            color: var(--text);
            font-size: 1.65rem;
            font-weight: 750;
            margin-top: 0.25rem;
          }
          .metric-note {
            color: var(--subtle);
            font-size: 0.82rem;
            margin-top: 0.15rem;
          }
          .scenario-note {
            color: var(--muted);
            font-size: 0.82rem;
            line-height: 1.35;
            min-height: 56px;
            border: 1px solid transparent;
            padding: 0.45rem 0.2rem;
          }
          .scenario-note.active {
            color: var(--text);
          }
          .evidence-panel strong {
            color: var(--text);
            display: block;
            margin-bottom: 0.4rem;
          }
          .evidence-panel p {
            color: var(--muted);
            margin: 0;
            line-height: 1.45;
          }
          .answer-summary {
            border: 1px solid rgba(103, 193, 181, 0.35);
            background: rgba(103, 193, 181, 0.08);
            border-radius: 8px;
            padding: 0.9rem 1rem;
            margin: 1rem 0;
          }
          .answer-summary strong {
            color: var(--accent);
            display: block;
            margin-bottom: 0.35rem;
          }
          .answer-summary p {
            color: #d7dde8;
            margin: 0;
            line-height: 1.55;
          }
          div[data-testid="stExpander"] {
            border: 1px solid var(--border);
            background: var(--panel-soft);
            border-radius: 8px;
            margin: 0.45rem 0;
          }
          div[data-testid="stExpander"] summary {
            color: var(--text);
            font-weight: 650;
          }
          .fact-detail {
            color: var(--text);
          }
          .fact-badges {
            margin-bottom: 0.6rem;
          }
          .fact-meta-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.55rem 1rem;
          }
          .fact-meta-grid span {
            color: var(--subtle);
            display: block;
            font-size: 0.75rem;
            margin-bottom: 0.1rem;
          }
          .fact-meta-grid strong {
            color: var(--text);
            font-size: 0.88rem;
            font-weight: 600;
            word-break: break-word;
          }
          .detail-heading {
            color: var(--accent);
            font-size: 0.8rem;
            font-weight: 700;
            margin-top: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
          }
          .condition-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 0.35rem;
            font-size: 0.88rem;
          }
          .condition-table td {
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding: 0.35rem 0.2rem;
          }
          .condition-table td:first-child {
            color: var(--muted);
            width: 34%;
          }
          .quote-box {
            border-left: 3px solid var(--accent-2);
            color: #d7dde8;
            background: rgba(199, 179, 106, 0.08);
            padding: 0.55rem 0.7rem;
            margin-top: 0.35rem;
            line-height: 1.5;
          }
          .confidence {
            border-radius: 999px;
            padding: 0.12rem 0.55rem;
            font-size: 0.72rem;
            font-weight: 750;
            text-transform: uppercase;
          }
          .confidence.high {
            background: rgba(103, 193, 181, 0.14);
            color: var(--accent);
            border: 1px solid rgba(103, 193, 181, 0.35);
          }
          .confidence.medium {
            background: rgba(199, 179, 106, 0.14);
            color: var(--accent-2);
            border: 1px solid rgba(199, 179, 106, 0.35);
          }
          .confidence.low {
            background: rgba(211, 123, 123, 0.14);
            color: var(--danger);
            border: 1px solid rgba(211, 123, 123, 0.35);
          }
          .confidence.unknown {
            background: rgba(154, 164, 178, 0.14);
            color: var(--muted);
            border: 1px solid rgba(154, 164, 178, 0.35);
          }
          .gap-row,
          .entity-row {
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding: 0.55rem 0;
          }
          .gap-detail {
            color: var(--muted);
            font-size: 0.82rem;
            margin-top: 0.18rem;
          }
          .entity-row {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
            color: var(--muted);
          }
          .entity-row strong {
            color: var(--text);
          }
          .verification-box {
            color: #d7dde8;
            border-left: 3px solid var(--accent);
            padding: 0.75rem 0.9rem;
            background: rgba(103, 193, 181, 0.08);
            line-height: 1.55;
            margin: 1rem 0;
          }
          div[data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.7rem 0.85rem;
          }
          .sidebar-status {
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
            margin-top: 1rem;
          }
          .sidebar-status-label {
            color: var(--muted);
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
          }
          .sidebar-status-value {
            color: var(--text);
            font-size: 1.05rem;
            font-weight: 700;
            margin-top: 0.35rem;
          }
          .sidebar-status-note {
            color: var(--muted);
            font-size: 0.78rem;
            margin-top: 0.25rem;
          }
          .stTabs [data-baseweb="tab-list"] {
            gap: 0.25rem;
            border-bottom: 1px solid var(--border);
          }
          .stTabs [data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            color: var(--muted);
            padding: 0.55rem 0.85rem;
          }
          .stTabs [aria-selected="true"] {
            background: var(--panel);
            color: var(--text);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(
        page_title="Научный клубок — карта знаний R&D",
        layout="wide",
    )
    css()

    mtime = graph_mtime()
    stats = load_graph_stats(mtime)
    render_sidebar(stats)

    if stats.get("error"):
        st.error(stats["error"])
        return

    render_page_header(stats)

    overview_tab, answer_tab, search_tab, gap_tab, relations_tab, quality_tab = st.tabs(
        ["Обзор", "Аналитический ответ", "Поиск", "Матрица пробелов", "Связи", "Качество данных"]
    )

    with overview_tab:
        render_overview_tab(stats)

    with answer_tab:
        render_answer_tab()

    with search_tab:
        render_search_tab()

    with gap_tab:
        render_gap_tab(mtime)

    with relations_tab:
        render_relations_tab()

    with quality_tab:
        render_quality_tab(stats)


if __name__ == "__main__":
    main()
