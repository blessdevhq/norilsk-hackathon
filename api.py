from collections import Counter
from math import isnan
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from answer_synthesizer import build_answer
from gap_matrix import build_matrix, gaps
from query_graph import (
    find_facts,
    free_search,
    load_graph,
    neighbors,
    node_label,
    parse_number_range,
)


GRAPH_PATH = Path("graph.json")
DEMO_SOURCE_DOC_COUNT = 25
PREPARED_TXT_COUNT = 152

AXIS_LABELS = {
    "material": "Материалы",
    "process": "Процессы",
    "property": "Показатели",
}

CELL_STATES = [
    (0, 0, "empty", "не исследовано"),
    (1, 2, "single", "единичные данные"),
    (3, 5, "partial", "частично изучено"),
    (6, None, "covered", "изучено много"),
]

MOJIBAKE_MARKERS = (
    "Рџ",
    "Рњ",
    "Рќ",
    "РЎ",
    "Р”",
    "Р§",
    "РЁ",
    "СЃ",
    "С‚",
    "СЂ",
    "Р°",
    "Рµ",
    "Рё",
    "Рѕ",
    "Р»",
    "РЅ",
    "Рє",
)


class MatrixCellContext(BaseModel):
    row: str
    column: str
    axis1: str = "material"
    axis2: str = "process"
    count: int = 0
    condition_parameter: Optional[str] = None


class QueryRequest(BaseModel):
    query: str = ""
    filters: Dict[str, Any] = Field(default_factory=dict)
    matrixCell: Optional[MatrixCellContext] = None


class SubgraphRequest(BaseModel):
    facts: List[Dict[str, Any]] = Field(default_factory=list)
    matrixCell: Optional[MatrixCellContext] = None
    limit: int = 8


app = FastAPI(title="Научный клубок API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def repair_text(value: str) -> str:
    if not isinstance(value, str) or mojibake_score(value) == 0:
        return value

    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return value

    return repaired if mojibake_score(repaired) < mojibake_score(value) else value


def sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return repair_text(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            safe_key = repair_text(str(key)) if isinstance(key, str) else key
            sanitized[safe_key] = sanitize(item)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item) for item in value]
    if hasattr(value, "item"):
        try:
            return sanitize(value.item())
        except Exception:
            pass
    if isinstance(value, float) and isnan(value):
        return None
    return value


def graph_or_404():
    graph = load_graph(GRAPH_PATH)
    if graph is None:
        raise HTTPException(status_code=404, detail="graph.json не найден или не читается")
    return graph


def fact_key(fact: Dict[str, Any]) -> tuple:
    return (
        fact.get("material"),
        fact.get("process"),
        fact.get("result_property"),
        fact.get("result_value"),
        fact.get("result_unit"),
        fact.get("source_file"),
        fact.get("chunk_id"),
        fact.get("source_quote"),
    )


def merge_facts(*fact_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged = []
    seen = set()
    for facts in fact_groups:
        for fact in facts or []:
            if not isinstance(fact, dict):
                continue
            key = fact_key(fact)
            if key in seen:
                continue
            seen.add(key)
            merged.append(fact)
    return merged


def normalize_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "material",
        "process",
        "parameter",
        "value_min",
        "value_max",
        "unit",
        "result_value_min",
        "result_value_max",
        "result_unit",
        "year_min",
        "year_max",
        "geo",
        "geo_scope",
        "expert",
        "confidence",
        "property_query",
    }
    numeric = {"value_min", "value_max", "result_value_min", "result_value_max", "year_min", "year_max"}
    normalized = {}
    for key, value in (filters or {}).items():
        if key not in allowed or value in (None, ""):
            continue
        if key in numeric:
            try:
                value = int(value) if key.startswith("year_") else float(value)
            except (TypeError, ValueError):
                continue
        normalized[key] = value
    return normalized


def axis_filter(axis: str, label: str) -> Dict[str, Any]:
    if axis == "material":
        return {"material": label}
    if axis == "process":
        return {"process": label}
    if axis in {"property", "result", "result_property"}:
        return {"property_query": label}
    return {}


def facts_for_matrix_cell(cell: MatrixCellContext) -> List[Dict[str, Any]]:
    base_filter = axis_filter(cell.axis1, cell.row)
    if cell.condition_parameter:
        value_range = parse_number_range(cell.column)
        if value_range:
            return find_facts(
                **base_filter,
                parameter=cell.condition_parameter,
                value_min=value_range[0],
                value_max=value_range[1],
            )
        return find_facts(**base_filter, parameter=cell.condition_parameter)

    filters = {**base_filter, **axis_filter(cell.axis2, cell.column)}
    return find_facts(**filters) if filters else []


def related_facts_for_gap(cell: MatrixCellContext) -> List[Dict[str, Any]]:
    row_facts = find_facts(**axis_filter(cell.axis1, cell.row))
    if cell.condition_parameter:
        column_facts = find_facts(parameter=cell.condition_parameter)
    else:
        column_facts = find_facts(**axis_filter(cell.axis2, cell.column))
    return merge_facts(row_facts, column_facts)


def cell_state(count: int) -> Dict[str, str]:
    for start, end, key, label in CELL_STATES:
        if count >= start and (end is None or count <= end):
            return {"state": key, "stateLabel": label}
    return {"state": "covered", "stateLabel": "изучено много"}


def top_entities(graph, node_type: str, limit: int = 7) -> List[Dict[str, Any]]:
    rows = []
    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != node_type:
            continue
        mentions = data.get("mention_count")
        try:
            weight = int(mentions) if mentions is not None else int(graph.degree(node_id))
        except Exception:
            weight = 0
        rows.append(
            {
                "id": node_id,
                "name": node_label(data) or data.get("name") or node_id,
                "mentions": weight,
                "type": node_type,
            }
        )
    rows.sort(key=lambda item: (-item["mentions"], str(item["name"])))
    return rows[:limit]


def confidence_distribution(graph) -> List[Dict[str, Any]]:
    counter = Counter()
    for _, _, data in graph.edges(data=True):
        if data.get("edge_type") != "yields":
            continue
        counter[str(data.get("confidence") or "unknown").lower()] += 1
    order = [("high", "Высокая"), ("medium", "Средняя"), ("low", "Низкая"), ("unknown", "Не указана")]
    return [{"key": key, "label": label, "value": counter.get(key, 0)} for key, label in order]


def presets() -> List[Dict[str, Any]]:
    return [
        {
            "label": "Обессоливание воды",
            "query": "шахтные воды обратный осмос сульфаты хлориды сухой остаток",
            "status": "частично найдено",
            "description": "Смежные методы очистки есть, точная связка Ca/Mg/Na и сухого остатка остается зоной добора источников.",
            "filters": {"material": "шахтные воды", "process": "обратный осмос"},
        },
        {
            "label": "Циркуляция католита",
            "query": "католит циркуляция скорость потока электроэкстракция никеля",
            "status": "частично найдено",
            "description": "Есть факты по электролиту, скорости потока и электроэкстракции, но не вся схема циркуляции закрыта.",
            "filters": {"process": "электроэкстракция", "parameter": "скорость"},
        },
        {
            "label": "Au/Ag/МПГ: штейн и шлак",
            "query": "Au Ag МПГ штейн шлак распределение",
            "status": "частично найдено",
            "description": "Найдены факты по МПГ, шлакам и штейнам; полный срез за пять лет остается зоной расширения корпуса.",
            "filters": {"material": "МПГ"},
        },
        {
            "label": "Закачка шахтных вод",
            "query": "закачка шахтных вод глубокие горизонты",
            "status": "пробел",
            "description": "Корпус больше покрывает очистку шахтных вод, чем закачку в глубокие горизонты и технико-экономику.",
            "filters": {},
        },
    ]


@app.get("/api/dashboard")
def dashboard():
    graph = graph_or_404()
    node_types = Counter(data.get("node_type") for _, data in graph.nodes(data=True))
    edge_types = Counter(data.get("edge_type") for _, _, data in graph.edges(data=True))

    response = {
        "graph": {
            "updatedAt": graph.graph.get("updated_at"),
            "verificationStatus": graph.graph.get("verification_status"),
            "source": graph.graph.get("source"),
        },
        "counts": {
            "nodes": graph.number_of_nodes(),
            "links": graph.number_of_edges(),
            "documents": node_types.get("Document", 0),
            "facts": edge_types.get("yields", 0),
            "materials": node_types.get("Material", 0),
            "processes": node_types.get("Process", 0),
            "properties": node_types.get("Property", 0),
            "experts": node_types.get("Expert", 0),
            "equipment": node_types.get("Equipment", 0),
            "demoDocuments": DEMO_SOURCE_DOC_COUNT,
            "preparedTxt": PREPARED_TXT_COUNT,
        },
        "confidence": confidence_distribution(graph),
        "topEntities": {
            "materials": top_entities(graph, "Material"),
            "processes": top_entities(graph, "Process"),
            "properties": top_entities(graph, "Property"),
            "experts": top_entities(graph, "Expert"),
        },
        "presets": presets(),
    }
    return sanitize(response)


@app.post("/api/query")
def query(request: QueryRequest):
    title = request.query.strip() or "Выбранная связка"
    filters = normalize_filters(request.filters)

    if request.matrixCell:
        cell_facts = facts_for_matrix_cell(request.matrixCell)
        if cell_facts:
            facts = cell_facts
        else:
            facts = related_facts_for_gap(request.matrixCell)
        title = f"{request.matrixCell.row} x {request.matrixCell.column}"
    else:
        query_text = request.query.strip()
        text_facts = []
        if query_text:
            text_facts = merge_facts(
                free_search(query_text),
                find_facts(material=query_text),
                find_facts(process=query_text),
                find_facts(property_query=query_text),
            )
        filter_facts = find_facts(**filters) if filters else []
        facts = merge_facts(text_facts, filter_facts)

    answer = build_answer(title, facts)

    if request.matrixCell and request.matrixCell.count == 0:
        answer["summary"] = (
            f"В матрице нет подтвержденных фактов для связки «{request.matrixCell.row} x "
            f"{request.matrixCell.column}». Ниже показаны смежные источники по каждой стороне связки, "
            "чтобы быстро понять, откуда начинать план исследования."
        )
        answer["gaps"] = [
            {
                "gap": f"Не исследована связка: {request.matrixCell.row} x {request.matrixCell.column}",
                "detail": "Темы встречаются в корпусе по отдельности, но совместного подтвержденного факта нет.",
            },
            *answer.get("gaps", []),
        ]

    response = {
        "query": request.query,
        "filters": filters,
        "facts": facts[:80],
        "answer": answer,
    }
    return sanitize(response)


@app.get("/api/matrix")
def matrix(
    axis1: str = "material",
    axis2: str = "process",
    condition_parameter: Optional[str] = Query(default=None),
    top1: int = 15,
    top2: int = 10,
    min_mentions: int = 3,
):
    df = build_matrix(
        axis1=axis1,
        axis2=axis2,
        condition_parameter=condition_parameter or None,
        graph_path=GRAPH_PATH,
        top_n_axis1=top1,
        top_n_axis2=top2,
        min_mentions=min_mentions,
    )
    if df is None:
        raise HTTPException(status_code=500, detail="Матрица недоступна")

    examples = df.attrs.get("examples", {})
    cells = []
    for row in list(df.index):
        for column in list(df.columns):
            count = int(df.loc[row, column])
            cells.append(
                {
                    "row": row,
                    "column": column,
                    "count": count,
                    "examples": examples.get((row, column), [])[:3],
                    **cell_state(count),
                }
            )

    axis1_key = df.attrs.get("axis1", axis1)
    axis2_key = df.attrs.get("axis2", condition_parameter or axis2)
    gap_rows = []
    for item in gaps(df)[:12]:
        gap_rows.append(
            {
                "row": item.get(axis1_key),
                "column": item.get(axis2_key),
                "interest": int(item.get("interest", 0)),
                "rowTotal": int(item.get("axis1_total", 0)),
                "columnTotal": int(item.get("axis2_total", 0)),
                "axis1": axis1,
                "axis2": axis2,
                "condition_parameter": condition_parameter or None,
                "count": 0,
                **cell_state(0),
            }
        )

    response = {
        "axis1": axis1,
        "axis2": axis2,
        "condition_parameter": condition_parameter or None,
        "axisLabels": {"axis1": AXIS_LABELS.get(axis1, axis1), "axis2": AXIS_LABELS.get(axis2, axis2)},
        "rows": list(df.index),
        "columns": list(df.columns),
        "cells": cells,
        "gaps": gap_rows,
    }
    return sanitize(response)


@app.get("/api/relations")
def relation_rows(entity: str):
    if not entity.strip():
        return {"entity": entity, "rows": []}
    return sanitize({"entity": entity, "rows": neighbors(entity.strip())[:80]})


def graph_node(nodes: Dict[str, Dict[str, Any]], node_id: str, label: str, kind: str):
    if not label:
        return
    if node_id not in nodes:
        nodes[node_id] = {"id": node_id, "label": label, "kind": kind}


def graph_edge(edges: List[Dict[str, Any]], source: str, target: str, label: str):
    if source and target:
        edge_id = f"{source}->{target}:{label}"
        if not any(edge["id"] == edge_id for edge in edges):
            edges.append({"id": edge_id, "source": source, "target": target, "label": label})


def safe_id(prefix: str, value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in str(value or "").lower()).strip("_")
    return f"{prefix}:{cleaned[:64] or 'unknown'}"


@app.post("/api/subgraph")
def subgraph(request: SubgraphRequest):
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    facts = request.facts[: max(1, min(request.limit, 16))]
    for index, fact in enumerate(facts):
        material = fact.get("material")
        process = fact.get("process")
        prop = fact.get("result_property")
        source = fact.get("source_file")
        expert = fact.get("lab_or_author")

        material_id = safe_id("material", material)
        process_id = safe_id("process", process)
        prop_id = safe_id("property", prop)
        source_id = safe_id("document", source)
        expert_id = safe_id("expert", expert)

        graph_node(nodes, material_id, material, "material")
        graph_node(nodes, process_id, process, "process")
        graph_node(nodes, prop_id, prop, "property")
        graph_node(nodes, source_id, source, "document")
        graph_node(nodes, expert_id, expert, "expert")

        graph_edge(edges, material_id, process_id, "изучалось в")
        graph_edge(edges, process_id, prop_id, "влияет на")
        graph_edge(edges, process_id or material_id or prop_id, source_id, "описано в")
        graph_edge(edges, expert_id, process_id or material_id, "команда")

        if not any([material, process, prop]) and source:
            fact_id = f"fact:{index}"
            graph_node(nodes, fact_id, f"Факт {index + 1}", "fact")
            graph_edge(edges, fact_id, source_id, "источник")

    if not nodes and request.matrixCell:
        row_id = safe_id(request.matrixCell.axis1, request.matrixCell.row)
        col_id = safe_id(request.matrixCell.axis2, request.matrixCell.column)
        gap_id = "gap:selected"
        graph_node(nodes, row_id, request.matrixCell.row, request.matrixCell.axis1)
        graph_node(nodes, col_id, request.matrixCell.column, request.matrixCell.axis2)
        graph_node(nodes, gap_id, "Пробел", "gap")
        graph_edge(edges, row_id, gap_id, "нет подтверждения")
        graph_edge(edges, gap_id, col_id, "нет подтверждения")

    return sanitize({"nodes": list(nodes.values()), "edges": edges})
