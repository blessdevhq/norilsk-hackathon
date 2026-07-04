"""Экспорт карты знаний в JSON-LD.

JSON-LD делает граф Findable/Interoperable/Reusable по принципам FAIR:
каждая сущность и каждый факт получают @id, типизацию по онтологии домена
и провенанс (источник, цитата, confidence, дата актуализации).

Два режима:
- graph_to_jsonld(graph): весь граф (сущности + факты со связями);
- facts_to_jsonld(facts, title): результат конкретного запроса как
  самодостаточный набор фактов для вставки в отчёт/ТЗ.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

try:
    from query_graph import iter_fact_rows, load_graph, node_label
except Exception as exc:  # pragma: no cover - зависит от окружения
    iter_fact_rows = None
    load_graph = None
    node_label = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


ONTOLOGY = "https://nornickel.rnd/ontology#"
ENTITY_BASE = "https://nornickel.rnd/entity/"
FACT_BASE = "https://nornickel.rnd/fact/"

ENTITY_TYPES = {"Material", "Process", "Property", "Equipment", "Expert", "Document"}

JSONLD_CONTEXT = {
    "@vocab": ONTOLOGY,
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "qudt": "http://qudt.org/schema/qudt/",
    "name": "schema:name",
    "aliases": "skos:altLabel",
    "material": {"@id": "uses_material", "@type": "@id"},
    "process": {"@id": "applies_process", "@type": "@id"},
    "property": {"@id": "measures_property", "@type": "@id"},
    "value": "qudt:numericValue",
    "unit": "qudt:unit",
    "confidence": "certaintyLevel",
    "verificationStatus": "prov:wasGeneratedBy",
    "sourceFile": "dcterms:source",
    "sourceQuote": "prov:value",
    "geoScope": "geographicScope",
    "locationGeo": "schema:locationCreated",
    "expert": "dcterms:creator",
    "year": "dcterms:date",
    "updatedAt": "dcterms:modified",
    "derivedFrom": {"@id": "prov:wasDerivedFrom", "@type": "@id"},
}


def _iri(base, value):
    text = str(value or "unknown")
    return base + quote(text, safe="")


def entity_iri(node_id):
    return _iri(ENTITY_BASE, node_id)


def _fact_iri(fact):
    parts = [
        str(fact.get("_material_id")),
        str(fact.get("_process_id")),
        str(fact.get("_property_id")),
        str(fact.get("result_value")),
        str(fact.get("source_file")),
        str(fact.get("chunk_id")),
        str(fact.get("source_quote")),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return FACT_BASE + digest


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _entity_items(graph):
    items = []
    for node_id, data in graph.nodes(data=True):
        node_type = data.get("node_type")
        if node_type not in ENTITY_TYPES:
            continue
        item = {
            "@id": entity_iri(node_id),
            "@type": node_type,
            "name": node_label(data) or data.get("name") or node_id,
        }
        aliases = data.get("aliases")
        if isinstance(aliases, list) and aliases:
            item["aliases"] = sorted({str(alias) for alias in aliases if alias})
        if data.get("category"):
            item["dcterms:type"] = data.get("category")
        items.append(item)
    return items


def _conditions_jsonld(conditions):
    rows = []
    if not isinstance(conditions, list):
        return rows
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        row = {
            "@type": "ProcessCondition",
            "parameter": _clean(condition.get("parameter")),
            "value": condition.get("value"),
            "unit": _clean(condition.get("unit")),
        }
        rows.append({key: val for key, val in row.items() if val is not None})
    return rows


def _fact_item(fact, with_links=True):
    item = {
        "@id": _fact_iri(fact),
        "@type": "ResearchFact",
        "name": _clean(fact.get("result_property")) or "результат",
    }
    if with_links:
        if fact.get("_material_id"):
            item["material"] = entity_iri(fact["_material_id"])
        if fact.get("_process_id"):
            item["process"] = entity_iri(fact["_process_id"])
        if fact.get("_property_id"):
            item["property"] = entity_iri(fact["_property_id"])
        if fact.get("source_file"):
            item["derivedFrom"] = _iri(ENTITY_BASE, "Document:" + str(fact["source_file"]))
    else:
        inline = {
            "material": _clean(fact.get("material")),
            "process": _clean(fact.get("process")),
            "property": _clean(fact.get("result_property")),
        }
        for key, value in inline.items():
            if value is not None:
                item[key] = value

    mapping = {
        "value": fact.get("result_value"),
        "unit": _clean(fact.get("result_unit")),
        "direction": _clean(fact.get("direction")),
        "confidence": _clean(fact.get("confidence")),
        "verificationStatus": _clean(fact.get("verification_status")),
        "sourceFile": _clean(fact.get("source_file")),
        "sourceQuote": _clean(fact.get("source_quote")),
        "year": fact.get("year"),
        "locationGeo": _clean(fact.get("location_geo")),
        "geoScope": _clean(fact.get("geo_scope")),
        "expert": _clean(fact.get("lab_or_author")),
        "equipment": _clean(fact.get("equipment")),
        "updatedAt": _clean(fact.get("updated_at")),
    }
    for key, value in mapping.items():
        if value is not None:
            item[key] = value

    conditions = _conditions_jsonld(fact.get("conditions"))
    if conditions:
        item["conditions"] = conditions
    return item


def graph_to_jsonld(graph):
    """Полный граф в JSON-LD: сущности + факты со связями."""
    if graph is None:
        raise ValueError("graph is None")

    items = _entity_items(graph)
    for fact, _material_data, _process_data, _property_data in iter_fact_rows(graph):
        items.append(_fact_item(fact, with_links=True))

    return {
        "@context": JSONLD_CONTEXT,
        "@id": "https://nornickel.rnd/knowledge-graph",
        "@type": "schema:Dataset",
        "name": "Научный клубок — карта знаний R&D",
        "dcterms:modified": graph.graph.get("updated_at"),
        "prov:wasGeneratedBy": graph.graph.get("verification_status"),
        "@graph": items,
    }


def facts_to_jsonld(facts, title="Результат запроса"):
    """Набор фактов запроса в JSON-LD (для экспорта ответа в отчёт/ТЗ)."""
    items = [_fact_item(fact, with_links=False) for fact in (facts or []) if isinstance(fact, dict)]
    return {
        "@context": JSONLD_CONTEXT,
        "@type": "schema:Dataset",
        "name": title,
        "dcterms:hasPart": len(items),
        "@graph": items,
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Export knowledge graph to JSON-LD")
    parser.add_argument("--graph", default="graph.json", help='Graph JSON path (default: "graph.json")')
    parser.add_argument("--output", default="graph.jsonld", help='Output JSON-LD path (default: "graph.jsonld")')
    return parser.parse_args()


def main():
    if load_graph is None:
        print(f"ERROR: cannot import query_graph -> {_IMPORT_ERROR}")
        raise SystemExit(1)

    args = parse_args()
    graph = load_graph(Path(args.graph))
    if graph is None:
        print(f"ERROR: cannot load graph from {args.graph}")
        raise SystemExit(1)

    document = graph_to_jsonld(graph)
    output_path = Path(args.output)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    entities = sum(1 for item in document["@graph"] if item.get("@type") in ENTITY_TYPES)
    facts = sum(1 for item in document["@graph"] if item.get("@type") == "ResearchFact")
    print(f"JSON-LD saved: {output_path} (entities={entities}, facts={facts})")


if __name__ == "__main__":
    main()
