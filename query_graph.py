import argparse
import json
import re
from pathlib import Path

from units import convert_range, is_known_unit, same_dimension

try:
    import networkx as nx
    from networkx.readwrite import json_graph
except Exception as exc:
    nx = None
    json_graph = None
    NETWORKX_IMPORT_ERROR = exc
else:
    NETWORKX_IMPORT_ERROR = None


GRAPH_PATH = Path("graph.json")
SYNONYMS_PATH = Path("synonyms.json")
ENTITY_TYPES_FOR_SEARCH = {"Material", "Process", "Property", "Equipment", "Expert"}
RU_SEARCH_ENDINGS = (
    "ыми",
    "ими",
    "ого",
    "его",
    "ому",
    "ему",
    "ами",
    "ями",
    "ах",
    "ях",
    "ой",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ов",
    "ев",
    "ом",
    "ем",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "ь",
)

_GRAPH_CACHE = None
_GRAPH_CACHE_PATH = None
_QUERY_SYNONYM_MAP = None


def load_graph(path=GRAPH_PATH):
    global _GRAPH_CACHE, _GRAPH_CACHE_PATH

    path = Path(path)
    if _GRAPH_CACHE is not None and _GRAPH_CACHE_PATH == path:
        return _GRAPH_CACHE

    if nx is None:
        print("")
        print("ERROR: networkx is not installed or cannot be imported.")
        print(f"Import error: {NETWORKX_IMPORT_ERROR}")
        print("Install dependency: pip install networkx")
        return None

    if not path.exists():
        print(f"ERROR: graph file does not exist: {path}")
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: cannot read graph JSON {path} -> {exc}")
        return None

    try:
        try:
            graph = json_graph.node_link_graph(data, edges="links")
        except TypeError:
            graph = json_graph.node_link_graph(data)
    except Exception as exc:
        print(f"ERROR: cannot load NetworkX graph from {path} -> {exc}")
        return None

    _GRAPH_CACHE = graph
    _GRAPH_CACHE_PATH = path
    return graph


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).lower()


def load_query_synonym_map(path=SYNONYMS_PATH):
    global _QUERY_SYNONYM_MAP

    if _QUERY_SYNONYM_MAP is not None:
        return _QUERY_SYNONYM_MAP

    mapping = {}
    path = Path(path)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"WARNING: cannot read query synonyms {path} -> {exc}")
            raw = {}

        if isinstance(raw, dict):
            for canonical, aliases in raw.items():
                canonical_text = clean_text(canonical)
                if not canonical_text:
                    continue
                mapping[canonical_text] = canonical_text
                if isinstance(aliases, list):
                    for alias in aliases:
                        alias_text = clean_text(alias)
                        if alias_text:
                            mapping[alias_text] = canonical_text

    _QUERY_SYNONYM_MAP = mapping
    return mapping


def query_variants(value):
    text = clean_text(value)
    if not text:
        return []
    if not split_words(text):
        return []

    variants = [text]
    canonical = load_query_synonym_map().get(text)
    if canonical and canonical not in variants:
        variants.append(canonical)

    return variants


def node_label(data):
    return data.get("display_name") or data.get("name") or data.get("text")


def node_search_texts(data, include_base=False):
    texts = [
        data.get("name"),
        data.get("display_name"),
        data.get("text"),
    ]

    aliases = data.get("aliases")
    if isinstance(aliases, list):
        texts.extend(aliases)

    if include_base:
        texts.append(data.get("base"))

    return [clean_text(text) for text in texts if clean_text(text)]


def text_filter_matches(value, data, include_base=False):
    needle = clean_text(value)
    if not needle:
        return True
    variants = query_variants(needle)
    if not variants:
        return False

    for text in node_search_texts(data, include_base=include_base):
        for variant in variants:
            if variant in text:
                return True
            variant_words = split_words(variant)
            if variant_words and words_match_text(variant_words, text, require_all=True):
                return True
    return False


def field_text_matches(value, actual):
    needle = clean_text(value)
    if not needle:
        return True
    variants = query_variants(needle)
    if not variants:
        return False

    haystack = clean_text(actual)
    if not haystack:
        return False

    for variant in variants:
        if variant in haystack:
            return True
        variant_words = split_words(variant)
        if variant_words and words_match_text(variant_words, haystack, require_all=True):
            return True

    return False


def unit_matches(actual, expected):
    expected_text = clean_unit_text(expected)
    if not expected_text:
        return True

    actual_text = clean_unit_text(actual)
    if not actual_text:
        return False

    return expected_text in actual_text or actual_text in expected_text


def clean_unit_text(value):
    text = clean_text(value)
    text = text.replace("³", "3")
    text = text.replace("²", "2")
    text = text.replace("℃", "°c")
    text = text.replace("°с", "°c")
    return text


def parse_number_range(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number, number

    text = str(value)
    text = text.replace(",", ".")
    text = text.replace("−", "-")
    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("~", " ")
    text = text.replace("∼", " ")
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " ", text)

    numbers = []
    for match in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            numbers.append(float(match.group(0)))
        except Exception:
            continue

    if not numbers:
        return None

    return min(numbers), max(numbers)


def ranges_intersect(actual_range, query_min=None, query_max=None):
    if actual_range is None:
        return False

    actual_min, actual_max = actual_range
    if query_min is None:
        query_min = float("-inf")
    else:
        query_min = float(query_min)

    if query_max is None:
        query_max = float("inf")
    else:
        query_max = float(query_max)

    return actual_max >= query_min and actual_min <= query_max


def year_matches(year, year_min=None, year_max=None):
    if year_min is None and year_max is None:
        return True
    year_range = parse_number_range(year)
    return ranges_intersect(year_range, year_min, year_max)


def edge_fact_key(edge_data):
    return (
        edge_data.get("source_file"),
        edge_data.get("chunk_id"),
        edge_data.get("source_quote"),
    )


def build_studied_index(graph):
    studied = {}
    for source, target, key, data in graph.edges(keys=True, data=True):
        if data.get("edge_type") != "studied_in":
            continue
        studied.setdefault((target, edge_fact_key(data)), []).append((source, data))
    return studied


def fact_from_edges(graph, material_id, material_data, process_id, process_data, property_id, property_data, edge_data):
    return {
        "material": node_label(material_data) if material_data else None,
        "process": node_label(process_data) if process_data else None,
        "result_property": node_label(property_data) if property_data else None,
        "result_value": edge_data.get("value"),
        "result_unit": edge_data.get("unit"),
        "direction": edge_data.get("direction"),
        "conditions": edge_data.get("conditions") if isinstance(edge_data.get("conditions"), list) else [],
        "source_file": edge_data.get("source_file"),
        "source_quote": edge_data.get("source_quote"),
        "chunk_id": edge_data.get("chunk_id"),
        "confidence": edge_data.get("confidence"),
        "year": edge_data.get("year"),
        "location_geo": edge_data.get("location_geo"),
        "geo_scope": edge_data.get("geo_scope"),
        "lab_or_author": edge_data.get("lab_or_author"),
        "equipment": edge_data.get("equipment"),
        "verification_status": edge_data.get("verification_status"),
        "updated_at": edge_data.get("updated_at"),
        "_material_id": material_id,
        "_process_id": process_id,
        "_property_id": property_id,
    }


def iter_fact_rows(graph):
    studied = build_studied_index(graph)

    for process_id, property_id, key, edge_data in graph.edges(keys=True, data=True):
        if edge_data.get("edge_type") != "yields":
            continue

        process_data = graph.nodes.get(process_id, {})
        property_data = graph.nodes.get(property_id, {})
        fact_key = edge_fact_key(edge_data)
        material_edges = studied.get((process_id, fact_key), [])

        if not material_edges:
            fact = fact_from_edges(
                graph,
                None,
                None,
                process_id,
                process_data,
                property_id,
                property_data,
                edge_data,
            )
            yield fact, {}, process_data, property_data
            continue

        for material_id, material_edge_data in material_edges:
            material_data = graph.nodes.get(material_id, {})
            fact = fact_from_edges(
                graph,
                material_id,
                material_data,
                process_id,
                process_data,
                property_id,
                property_data,
                edge_data,
            )
            if fact.get("source_quote") is None:
                fact["source_quote"] = material_edge_data.get("source_quote")
            yield fact, material_data, process_data, property_data


def condition_matches(condition, parameter=None, value_min=None, value_max=None, unit=None):
    if parameter is not None:
        parameter_text = clean_text(condition.get("parameter"))
        if clean_text(parameter) not in parameter_text:
            return False

    cond_unit = condition.get("unit")

    if value_min is not None or value_max is not None:
        value_range = parse_number_range(condition.get("value"))
        if value_range is None:
            return False
        if unit is not None:
            converted = convert_range(value_range, cond_unit, unit)
            if converted is not None:
                value_range = converted
            elif is_known_unit(cond_unit) and is_known_unit(unit):
                return False
            elif not unit_matches(cond_unit, unit):
                return False
        if not ranges_intersect(value_range, value_min, value_max):
            return False
        return True

    if unit is not None:
        if is_known_unit(cond_unit) and is_known_unit(unit):
            return same_dimension(cond_unit, unit)
        if not unit_matches(cond_unit, unit):
            return False

    return True


def conditions_match(conditions, parameter=None, value_min=None, value_max=None, unit=None):
    if parameter is None and value_min is None and value_max is None and unit is None:
        return True

    if not isinstance(conditions, list):
        return False

    for condition in conditions:
        if isinstance(condition, dict) and condition_matches(condition, parameter, value_min, value_max, unit):
            return True

    return False


def public_fact(fact):
    return {key: value for key, value in fact.items() if not key.startswith("_")}


def find_facts(
    material=None,
    process=None,
    parameter=None,
    value_min=None,
    value_max=None,
    unit=None,
    result_value_min=None,
    result_value_max=None,
    result_unit=None,
    year_min=None,
    year_max=None,
    geo=None,
    geo_scope=None,
    expert=None,
    confidence=None,
    property_query=None,
):
    graph = load_graph()
    if graph is None:
        return []

    results = []
    for fact, material_data, process_data, property_data in iter_fact_rows(graph):
        if material is not None and not material_data:
            continue
        if material is not None and not text_filter_matches(material, material_data):
            continue
        if process is not None and not text_filter_matches(process, process_data):
            continue
        if property_query is not None and not text_filter_matches(property_query, property_data):
            continue
        if not conditions_match(fact.get("conditions"), parameter, value_min, value_max, unit):
            continue

        if result_unit is not None:
            fact_unit = fact.get("result_unit")
            if is_known_unit(fact_unit) and is_known_unit(result_unit):
                if not same_dimension(fact_unit, result_unit):
                    continue
            elif not unit_matches(fact_unit, result_unit):
                continue
        if confidence is not None and clean_text(fact.get("confidence")) != clean_text(confidence):
            continue
        if not year_matches(fact.get("year"), year_min, year_max):
            continue
        if geo is not None and not field_text_matches(geo, fact.get("location_geo")):
            continue
        if geo_scope is not None and clean_text(fact.get("geo_scope")) != clean_text(geo_scope):
            continue
        if expert is not None and not field_text_matches(expert, fact.get("lab_or_author")):
            continue

        if result_value_min is not None or result_value_max is not None:
            result_range = parse_number_range(fact.get("result_value"))
            if result_range is None:
                continue
            if result_unit is not None:
                converted_result = convert_range(result_range, fact.get("result_unit"), result_unit)
                if converted_result is not None:
                    result_range = converted_result
            if not ranges_intersect(result_range, result_value_min, result_value_max):
                continue

        results.append(public_fact(fact))

    return results


def find_matching_nodes(graph, query_text, include_base=False):
    variants = query_variants(query_text)
    if not variants:
        return []

    matches = []
    for node_id, data in graph.nodes(data=True):
        node_type = data.get("node_type")
        if node_type not in ENTITY_TYPES_FOR_SEARCH:
            continue

        texts = node_search_texts(data, include_base=include_base)
        for variant in variants:
            words = split_words(variant)
            if not words:
                continue
            min_matches = len(words) if len(words) <= 2 else 2
            if any(variant in text for text in texts):
                matches.append((node_id, data))
                break
            if any(words_match_text(words, text, min_matches=min_matches) for text in texts):
                matches.append((node_id, data))
                break

    return matches


def process_name_for_edge(graph, source, target, data):
    source_data = graph.nodes.get(source, {})
    target_data = graph.nodes.get(target, {})

    if source_data.get("node_type") == "Process":
        return node_label(source_data)
    if target_data.get("node_type") == "Process":
        return node_label(target_data)

    return None


def neighbor_row(graph, entity_id, entity_data, source, target, data, direction):
    related_id = target if direction == "out" else source
    related_data = graph.nodes.get(related_id, {})

    return {
        "entity": node_label(entity_data),
        "entity_type": entity_data.get("node_type"),
        "related_entity": node_label(related_data),
        "related_type": related_data.get("node_type"),
        "direction": direction,
        "edge_type": data.get("edge_type"),
        "process": process_name_for_edge(graph, source, target, data),
        "source_file": data.get("source_file"),
        "source_quote": data.get("source_quote"),
        "chunk_id": data.get("chunk_id"),
        "confidence": data.get("confidence"),
        "year": data.get("year"),
        "location_geo": data.get("location_geo"),
        "geo_scope": data.get("geo_scope"),
        "lab_or_author": data.get("lab_or_author"),
        "equipment": data.get("equipment"),
        "verification_status": data.get("verification_status"),
        "updated_at": data.get("updated_at"),
        "value": data.get("value"),
        "unit": data.get("unit"),
        "conditions": data.get("conditions") if isinstance(data.get("conditions"), list) else [],
    }


def neighbors(entity_name):
    graph = load_graph()
    if graph is None:
        return []

    matched_nodes = find_matching_nodes(graph, entity_name, include_base=True)
    rows = []

    for entity_id, entity_data in matched_nodes:
        try:
            out_edges = graph.out_edges(entity_id, keys=True, data=True)
            for source, target, key, data in out_edges:
                rows.append(neighbor_row(graph, entity_id, entity_data, source, target, data, "out"))
        except Exception as exc:
            print(f"ERROR: cannot read outgoing edges for {entity_id} -> {exc}")

        try:
            in_edges = graph.in_edges(entity_id, keys=True, data=True)
            for source, target, key, data in in_edges:
                rows.append(neighbor_row(graph, entity_id, entity_data, source, target, data, "in"))
        except Exception as exc:
            print(f"ERROR: cannot read incoming edges for {entity_id} -> {exc}")

    return rows


def split_words(text):
    words = []
    for word in re.findall(r"[A-Za-zА-Яа-яЁё0-9_+-]+", str(text).lower()):
        word = word.strip("_+-")
        if len(word) >= 2:
            words.append(word)
    return words


def word_variants(word):
    variants = {word}
    for ending in RU_SEARCH_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            variants.add(word[: -len(ending)])
            break
    return variants


def words_match_text(words, text, require_all=False, min_matches=None):
    if not words:
        return False

    text = clean_text(text)
    if not text:
        return False

    matched = 0
    for word in words:
        if any(variant and variant in text for variant in word_variants(word)):
            matched += 1

    if require_all:
        return matched == len(words)
    if min_matches is None:
        min_matches = 1
    return matched >= min_matches


def equipment_process_ids(graph, equipment_ids):
    process_ids = set()
    for equipment_id in equipment_ids:
        try:
            for source, target, key, data in graph.in_edges(equipment_id, keys=True, data=True):
                if data.get("edge_type") == "uses_equipment":
                    process_ids.add(source)
        except Exception as exc:
            print(f"ERROR: cannot read equipment edges for {equipment_id} -> {exc}")
    return process_ids


def fact_unique_key(fact):
    return (
        fact.get("_material_id"),
        fact.get("_process_id"),
        fact.get("_property_id"),
        fact.get("result_value"),
        fact.get("result_unit"),
        fact.get("source_file"),
        fact.get("chunk_id"),
        fact.get("source_quote"),
    )


def free_search(query_text):
    graph = load_graph()
    if graph is None:
        return []

    matched_nodes = find_matching_nodes(graph, query_text, include_base=True)
    if not matched_nodes:
        return []

    matched_by_id = {node_id: data for node_id, data in matched_nodes}
    equipment_ids = {
        node_id for node_id, data in matched_nodes if data.get("node_type") == "Equipment"
    }
    equipment_processes = equipment_process_ids(graph, equipment_ids)
    expert_matches = [
        (node_id, node_label(data))
        for node_id, data in matched_nodes
        if data.get("node_type") == "Expert"
    ]

    results = []
    seen = set()

    for fact, material_data, process_data, property_data in iter_fact_rows(graph):
        matched_id = None

        for node_id in (fact.get("_material_id"), fact.get("_process_id"), fact.get("_property_id")):
            if node_id in matched_by_id:
                matched_id = node_id
                break

        if matched_id is None and fact.get("_process_id") in equipment_processes:
            for equipment_id in equipment_ids:
                matched_id = equipment_id
                break

        if matched_id is None:
            for expert_id, expert_name in expert_matches:
                if field_text_matches(expert_name, fact.get("lab_or_author")):
                    matched_id = expert_id
                    break

        if matched_id is None:
            continue

        unique_key = fact_unique_key(fact)
        if unique_key in seen:
            continue
        seen.add(unique_key)

        result = public_fact(fact)
        matched_data = matched_by_id.get(matched_id, {})
        result["matched_entity"] = node_label(matched_data)
        result["matched_entity_type"] = matched_data.get("node_type")
        results.append(result)

    return results


def print_facts(facts, limit):
    print(f"Facts found: {len(facts)}")
    for fact in facts[:limit]:
        value = fact.get("result_value")
        unit = fact.get("result_unit") or ""
        if value is None:
            value_text = ""
        else:
            value_text = f" = {value} {unit}".strip()

        print(
            " | ".join(
                [
                    str(fact.get("material") or "?"),
                    str(fact.get("process") or "?"),
                    f"{fact.get('result_property') or '?'}{value_text}",
                    str(fact.get("source_file") or "?"),
                    str(fact.get("source_quote") or ""),
                ]
            )
        )

    if len(facts) > limit:
        print(f"... {len(facts) - limit} more facts not printed")


def parse_args():
    parser = argparse.ArgumentParser(description="Search facts in graph.json")
    parser.add_argument("query", help="Search text, for example: nickel")
    parser.add_argument("--graph", default=str(GRAPH_PATH), help='Graph JSON path (default: "graph.json")')
    parser.add_argument("--limit", type=int, default=30, help="Max facts to print")
    return parser.parse_args()


def main():
    global GRAPH_PATH

    args = parse_args()
    GRAPH_PATH = Path(args.graph)
    facts = free_search(args.query)
    print_facts(facts, args.limit)


if __name__ == "__main__":
    main()
