import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import networkx as nx
    from networkx.readwrite import json_graph
except Exception as exc:
    nx = None
    json_graph = None
    NETWORKX_IMPORT_ERROR = exc
else:
    NETWORKX_IMPORT_ERROR = None


INPUT_PATH = Path("facts.jsonl")
OUTPUT_PATH = Path("graph.json")
REPORT_PATH = Path("normalization_report.txt")
SYNONYMS_PATH = Path("synonyms.json")

NULL_STRINGS = {"", "null", "none", "нет", "не указано"}
EQUIPMENT_MIN_COUNT = 2

STARTER_SYNONYMS = {
    "цианидное выщелачивание": ["цианирование"],
    "обеднение шлака": ["обеднение шлаков", "обеднение"],
    "руда": ["руды"],
    "медно-никелевый шлак": ["медно-никелевые шлаки"],
    "никелевый конвертерный шлак": [
        "никелевые конвертерные шлаки",
        "конвертерный никелевый шлак",
    ],
    "медно-никелевый штейн": ["медно-никелевые штейны"],
    "шахтные воды": ["шахтная вода", "шахтные вод", "шахтная вод"],
    "кислые шахтные воды": [
        "кислые шахтные вод",
        "кислые шахтные воды (miw)",
        "miw (кислые шахтные воды)",
        "miw",
    ],
    "шахтные сточные воды": ["шахтные сточные вод"],
    "автоклавное окислительное выщелачивание": [
        "окислительное автоклавное выщелачивание",
        "pox (автоклавное окислительное выщелачивание)",
        "pox (окислительное выщелачивание)",
    ],
    "смешанные сульфиды": ["смешанный сульфид", "сульфид (сс)"],
    "металлизированная фракция файнштейна": [
        "металлизированная фракция (мф) файнштейна",
    ],
    "cu-nahs фильтрат": ["фильтрат cu-nahs"],
    "жидко-фазная экстракция": [
        "жидко-фазная экстракция (cosx)",
        "жидко-фазная экстракция (isx)",
    ],
}


def collapse_spaces(text):
    return re.sub(r"\s+", " ", text.strip())


def clean_value(value):
    if isinstance(value, dict):
        return {key: clean_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in NULL_STRINGS:
            return None
        return collapse_spaces(text)
    return value


def normalize_layer1(value):
    if value is None:
        return None

    text = collapse_spaces(str(value))
    if not text:
        return None

    key = text.lower()
    return key


def remove_parentheses_fragments(name):
    return collapse_spaces(re.sub(r"\([^)]*\)", " ", name))


def split_base_variant(name):
    clean_name = remove_parentheses_fragments(name)
    if not clean_name:
        return None, None

    words = clean_name.split()
    if not words:
        return None, None
    if len(words) == 1:
        return words[0], None
    return words[-1], " ".join(words[:-1])


def is_short_latin_token(text):
    return (
        len(text) < 4
        and " " not in text
        and re.fullmatch(r"[A-Za-z0-9_./+-]+", text) is not None
        and re.search(r"[A-Za-z]", text) is not None
    )


def apply_parenthesized_alias_rule(name):
    match = re.fullmatch(r"(.+?)\s*\(([^()]*)\)\s*", name)
    if match is None:
        return name, []

    base_name = collapse_spaces(match.group(1))
    alias = collapse_spaces(match.group(2))
    if len(base_name) < 2:
        return name, []
    if is_short_latin_token(base_name):
        return name, []

    aliases = [alias] if alias else []
    return base_name, aliases


def normalize_entity_name(value, synonym_map):
    display_name = clean_value(value)
    if display_name is None:
        return None

    layer1_name = normalize_layer1(display_name)
    if layer1_name is None:
        return None

    canonical_name = synonym_map.get(layer1_name, layer1_name)
    canonical_name, extra_aliases = apply_parenthesized_alias_rule(canonical_name)
    base, variant = split_base_variant(canonical_name)

    return {
        "name": canonical_name,
        "display_name": display_name,
        "layer1_name": layer1_name,
        "extra_aliases": extra_aliases,
        "base": base,
        "variant": variant,
    }


def normalize_simple_name(value):
    display_name = clean_value(value)
    if display_name is None:
        return None

    name = normalize_layer1(display_name)
    if name is None:
        return None

    return {"name": name, "display_name": display_name}


def ensure_synonyms_file(path):
    if path.exists():
        return

    try:
        path.write_text(
            json.dumps(STARTER_SYNONYMS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Created starter synonyms file: {path}")
    except Exception as exc:
        print(f"ERROR: cannot create starter synonyms file {path} -> {exc}")


def load_synonym_map(path):
    raw_synonyms = STARTER_SYNONYMS

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw_synonyms = loaded
            else:
                print(f"ERROR: synonyms file is not a JSON object: {path}")
                raw_synonyms = {}
        except Exception as exc:
            print(f"ERROR: cannot read synonyms file {path} -> {exc}")
            raw_synonyms = {}
    else:
        print(f"WARNING: synonyms file not found, continuing without file: {path}")

    synonym_map = {}
    for canonical, aliases in raw_synonyms.items():
        canonical_name = normalize_layer1(canonical)
        if canonical_name is None:
            print(f"WARNING: skipped empty canonical synonym key: {canonical}")
            continue

        synonym_map[canonical_name] = canonical_name
        if not isinstance(aliases, list):
            print(f"WARNING: synonyms for '{canonical}' are not a list, skipped")
            continue

        for alias in aliases:
            alias_name = normalize_layer1(alias)
            if alias_name is None:
                continue
            if alias_name in synonym_map and synonym_map[alias_name] != canonical_name:
                print(
                    "WARNING: synonym collision: "
                    f"{alias_name} -> {synonym_map[alias_name]}, overwritten by {canonical_name}"
                )
            synonym_map[alias_name] = canonical_name

    print(f"Synonym rules loaded: {len(synonym_map)}")
    return synonym_map


def parse_args():
    parser = argparse.ArgumentParser(description="Build NetworkX graph from facts.jsonl")
    parser.add_argument("--input", default=str(INPUT_PATH), help='Input JSONL path (default: "facts.jsonl")')
    parser.add_argument("--output", default=str(OUTPUT_PATH), help='Output graph JSON path (default: "graph.json")')
    parser.add_argument(
        "--report",
        default=str(REPORT_PATH),
        help='Normalization report path (default: "normalization_report.txt")',
    )
    parser.add_argument(
        "--synonyms",
        default=str(SYNONYMS_PATH),
        help='Synonyms JSON path (default: "synonyms.json")',
    )
    return parser.parse_args()


def read_jsonl_records(path):
    records = []
    stats = {"lines": 0, "records": 0, "bad_json": 0, "bad_record": 0}

    try:
        handle = path.open("r", encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: cannot open input file {path} -> {exc}")
        return records, stats

    with handle:
        for line_number, line in enumerate(handle, start=1):
            stats["lines"] += 1
            line = line.strip()
            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"ERROR: bad JSON in {path}, line {line_number} -> {exc}")
                stats["bad_json"] += 1
                continue
            except Exception as exc:
                print(f"ERROR: cannot parse line {line_number} in {path} -> {exc}")
                stats["bad_json"] += 1
                continue

            if not isinstance(record, dict):
                print(f"ERROR: JSONL record is not an object: line {line_number}")
                stats["bad_record"] += 1
                continue

            records.append((line_number, clean_value(record)))
            stats["records"] += 1

            if stats["records"] % 1000 == 0:
                print(f"  records loaded: {stats['records']}")

    return records, stats


def get_dict(record, key, line_number):
    value = record.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        print(f"WARNING: field '{key}' is not an object: line {line_number}")
        return {}
    return value


def get_source_file(record, line_number):
    source_file = record.get("source_file")
    if source_file is None:
        print(f"WARNING: missing source_file: line {line_number}")
        return f"unknown_source_line_{line_number}"
    return collapse_spaces(str(source_file))


def get_chunk_id(record, line_number):
    chunk_id = record.get("chunk_id")
    if chunk_id is None:
        print(f"WARNING: missing chunk_id: line {line_number}")
    return chunk_id


def build_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_year(value):
    value = clean_value(value)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)

    match = re.search(r"\b(18|19|20)\d{2}\b", str(value))
    if match:
        return int(match.group(0))
    return value


def document_category(source_file):
    if "__" not in source_file:
        return None
    return source_file.split("__", 1)[0]


def node_id(node_type, name):
    return f"{node_type}:{name}"


def ensure_document_node(graph, source_file):
    doc_id = node_id("Document", source_file)
    if not graph.has_node(doc_id):
        graph.add_node(
            doc_id,
            node_type="Document",
            name=source_file,
            category=document_category(source_file),
        )
    return doc_id


def add_alias(node_data, alias):
    aliases = node_data.setdefault("aliases", [])
    if alias is not None and alias not in aliases:
        aliases.append(alias)


def ensure_material_node(graph, info, material_type):
    material_id = node_id("Material", info["name"])
    if not graph.has_node(material_id):
        graph.add_node(
            material_id,
            node_type="Material",
            name=info["name"],
            display_name=info["display_name"],
            aliases=[],
            base=info["base"],
            variant=info["variant"],
            material_type=material_type,
            material_types=[],
            mention_count=0,
        )

    data = graph.nodes[material_id]
    add_alias(data, info["display_name"])
    for alias in info.get("extra_aliases", []):
        add_alias(data, alias)
    data["mention_count"] = data.get("mention_count", 0) + 1
    if data.get("material_type") is None and material_type is not None:
        data["material_type"] = material_type
    if material_type is not None and material_type not in data.setdefault("material_types", []):
        data["material_types"].append(material_type)
    return material_id


def ensure_process_node(graph, info):
    process_id = node_id("Process", info["name"])
    if not graph.has_node(process_id):
        graph.add_node(
            process_id,
            node_type="Process",
            name=info["name"],
            display_name=info["display_name"],
            aliases=[],
            base=info["base"],
            variant=info["variant"],
            mention_count=0,
        )

    data = graph.nodes[process_id]
    add_alias(data, info["display_name"])
    for alias in info.get("extra_aliases", []):
        add_alias(data, alias)
    data["mention_count"] = data.get("mention_count", 0) + 1
    return process_id


def ensure_property_node(graph, info):
    property_id = node_id("Property", info["name"])
    if not graph.has_node(property_id):
        graph.add_node(
            property_id,
            node_type="Property",
            name=info["name"],
            display_name=info["display_name"],
            aliases=[],
            mention_count=0,
        )

    data = graph.nodes[property_id]
    add_alias(data, info["display_name"])
    data["mention_count"] = data.get("mention_count", 0) + 1
    return property_id


def ensure_equipment_node(graph, info, alias_counter, mention_count):
    equipment_id = node_id("Equipment", info["name"])
    if graph.has_node(equipment_id):
        return equipment_id

    aliases = list(alias_counter.keys())
    display_name = aliases[0] if aliases else info["display_name"]
    graph.add_node(
        equipment_id,
        node_type="Equipment",
        name=info["name"],
        display_name=display_name,
        aliases=aliases,
        mention_count=mention_count,
    )
    return equipment_id


def ensure_conclusion_node(graph, source_file, chunk_id, line_number, text, confidence):
    conclusion_id = f"Conclusion:{source_file}:{chunk_id}:{line_number}"
    if not graph.has_node(conclusion_id):
        graph.add_node(
            conclusion_id,
            node_type="Conclusion",
            text=text,
            confidence=confidence,
            source_file=source_file,
            chunk_id=chunk_id,
        )
    return conclusion_id


def add_typed_edge(graph, source, target, edge_type, attrs=None):
    data = {"edge_type": edge_type}
    if attrs:
        data.update(attrs)
    graph.add_edge(source, target, **data)


def collect_equipment_counts(records):
    equipment_counts = Counter()
    equipment_alias_counts = defaultdict(Counter)

    for line_number, record in records:
        if record.get("record_type") != "fact":
            continue
        context = get_dict(record, "context", line_number)
        equipment_info = normalize_simple_name(context.get("equipment"))
        if equipment_info is None:
            continue

        equipment_counts[equipment_info["name"]] += 1
        equipment_alias_counts[equipment_info["name"]][equipment_info["display_name"]] += 1

    allowed_equipment = {
        name for name, count in equipment_counts.items() if count >= EQUIPMENT_MIN_COUNT
    }
    print(
        "Equipment filter: "
        f"{len(equipment_counts)} unique, {len(allowed_equipment)} kept with count >= {EQUIPMENT_MIN_COUNT}"
    )
    return allowed_equipment, equipment_counts, equipment_alias_counts


def base_edge_attrs(record, source_file, chunk_id, updated_at):
    attrs = {
        "confidence": record.get("confidence"),
        "source_quote": record.get("source_quote"),
        "source_file": source_file,
        "chunk_id": chunk_id,
        "verification_status": "auto_extracted",
        "updated_at": updated_at,
    }

    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    context_fields = {
        "year": normalize_year(context.get("year")),
        "location_geo": clean_value(context.get("location_geo")),
        "lab_or_author": clean_value(context.get("lab_or_author")),
        "equipment": clean_value(context.get("equipment")),
    }
    for key, value in context_fields.items():
        if value is not None:
            attrs[key] = value

    return attrs


def build_graph(records, synonym_map):
    graph = nx.MultiDiGraph()
    updated_at = build_timestamp()
    graph.graph["updated_at"] = updated_at
    graph.graph["verification_status"] = "auto_extracted"
    allowed_equipment, equipment_counts, equipment_alias_counts = collect_equipment_counts(records)

    raw_material_counts = Counter()
    raw_process_counts = Counter()
    material_counts = Counter()
    process_counts = Counter()
    material_alias_counts = defaultdict(Counter)
    process_alias_counts = defaultdict(Counter)
    process_base_variant_by_name = {}
    record_type_counts = Counter()
    skipped_counts = Counter()

    for index, (line_number, record) in enumerate(records, start=1):
        if index % 500 == 0:
            print(f"  graph build progress: {index}/{len(records)} records")

        record_type = record.get("record_type")
        record_type_counts[record_type] += 1
        source_file = get_source_file(record, line_number)
        chunk_id = get_chunk_id(record, line_number)
        document_id = ensure_document_node(graph, source_file)

        if record_type == "conclusion":
            text = record.get("text")
            if text is None:
                print(f"WARNING: conclusion without text skipped: line {line_number}")
                skipped_counts["conclusion_without_text"] += 1
                continue

            conclusion_id = ensure_conclusion_node(
                graph,
                source_file,
                chunk_id,
                line_number,
                text,
                record.get("confidence"),
            )
            add_typed_edge(
                graph,
                conclusion_id,
                document_id,
                "from_document",
                {
                    "confidence": record.get("confidence"),
                    "source_file": source_file,
                    "chunk_id": chunk_id,
                    "verification_status": "auto_extracted",
                    "updated_at": updated_at,
                },
            )
            continue

        if record_type != "fact":
            print(f"WARNING: unknown record_type skipped: line {line_number}, record_type={record_type}")
            skipped_counts["unknown_record_type"] += 1
            continue

        material = get_dict(record, "material", line_number)
        process = get_dict(record, "process", line_number)
        result = get_dict(record, "result", line_number)
        context = get_dict(record, "context", line_number)

        material_info = normalize_entity_name(material.get("name"), synonym_map)
        process_info = normalize_entity_name(process.get("name"), synonym_map)
        property_info = normalize_simple_name(result.get("property"))
        equipment_info = normalize_simple_name(context.get("equipment"))

        if material_info is not None:
            raw_material_counts[material_info["display_name"]] += 1
            material_counts[material_info["name"]] += 1
            material_alias_counts[material_info["name"]][material_info["display_name"]] += 1

        if process_info is not None:
            raw_process_counts[process_info["display_name"]] += 1
            process_counts[process_info["name"]] += 1
            process_alias_counts[process_info["name"]][process_info["display_name"]] += 1
            process_base_variant_by_name[process_info["name"]] = (
                process_info["base"],
                process_info["variant"],
            )

        material_id = None
        process_id = None
        property_id = None

        if material_info is not None:
            material_id = ensure_material_node(graph, material_info, material.get("type"))

        if process_info is not None:
            process_id = ensure_process_node(graph, process_info)

        if property_info is not None:
            property_id = ensure_property_node(graph, property_info)

        edge_attrs = base_edge_attrs(record, source_file, chunk_id, updated_at)

        if material_id is not None:
            add_typed_edge(graph, material_id, document_id, "from_document", edge_attrs)

        if process_id is not None:
            add_typed_edge(graph, process_id, document_id, "from_document", edge_attrs)

        if material_id is not None and process_id is not None:
            add_typed_edge(graph, material_id, process_id, "studied_in", edge_attrs)

        if process_id is not None and property_id is not None:
            result_attrs = dict(edge_attrs)
            result_attrs.update(
                {
                    "value": result.get("value"),
                    "unit": result.get("unit"),
                    "direction": result.get("direction"),
                    "conditions": record.get("conditions") if isinstance(record.get("conditions"), list) else [],
                }
            )
            add_typed_edge(graph, process_id, property_id, "yields", result_attrs)
        elif process_id is not None:
            print(f"WARNING: fact without result.property, yields edge skipped: line {line_number}")
            skipped_counts["missing_property"] += 1

        if (
            process_id is not None
            and equipment_info is not None
            and equipment_info["name"] in allowed_equipment
        ):
            equipment_id = ensure_equipment_node(
                graph,
                equipment_info,
                equipment_alias_counts[equipment_info["name"]],
                equipment_counts[equipment_info["name"]],
            )
            add_typed_edge(graph, process_id, equipment_id, "uses_equipment", edge_attrs)

    stats = {
        "record_type_counts": record_type_counts,
        "skipped_counts": skipped_counts,
        "raw_material_counts": raw_material_counts,
        "raw_process_counts": raw_process_counts,
        "material_counts": material_counts,
        "process_counts": process_counts,
        "material_alias_counts": material_alias_counts,
        "process_alias_counts": process_alias_counts,
        "process_base_variant_by_name": process_base_variant_by_name,
    }
    return graph, stats


def edge_type_counts(graph):
    counts = Counter()
    for _, _, data in graph.edges(data=True):
        counts[data.get("edge_type", "unknown")] += 1
    return counts


def node_type_counts(graph):
    counts = Counter()
    for _, data in graph.nodes(data=True):
        counts[data.get("node_type", "unknown")] += 1
    return counts


def merge_rows(entity_type, alias_counts):
    rows = []
    for canonical, aliases in alias_counts.items():
        is_merge = len(aliases) > 1
        for alias in aliases:
            if normalize_layer1(alias) != canonical:
                is_merge = True
                break
        if not is_merge:
            continue
        rows.append((sum(aliases.values()), entity_type, canonical, aliases))
    rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    return rows


def process_base_groups(process_counts, process_base_variant_by_name):
    groups = defaultdict(Counter)
    for process_name, count in process_counts.items():
        base, variant = process_base_variant_by_name.get(
            process_name,
            split_base_variant(process_name),
        )
        if base is None:
            continue
        groups[base][variant or "(без варианта)"] += count
    return groups


def duplicate_signature(name):
    clean_name = remove_parentheses_fragments(name).lower()
    words = frozenset(word for word in clean_name.split() if word)
    if not words:
        return None
    return words


def duplicate_suspicions(entity_type, counts):
    groups = defaultdict(list)
    for name, count in counts.items():
        signature = duplicate_signature(name)
        if signature is None:
            continue
        groups[signature].append((name, count))

    rows = []
    for signature, names in groups.items():
        if len(names) < 2:
            continue
        names = sorted(names, key=lambda item: (-item[1], item[0]))
        for left_index in range(len(names)):
            for right_index in range(left_index + 1, len(names)):
                left_name, left_count = names[left_index]
                right_name, right_count = names[right_index]
                rows.append(
                    (
                        -(left_count + right_count),
                        entity_type,
                        " ".join(sorted(signature)),
                        left_name,
                        left_count,
                        right_name,
                        right_count,
                    )
                )

    rows.sort()
    return rows


def write_report(path, graph, stats):
    lines = []
    node_counts = node_type_counts(graph)
    edge_counts = edge_type_counts(graph)
    yields_edges = [
        data
        for _, _, data in graph.edges(data=True)
        if data.get("edge_type") == "yields"
    ]

    lines.append("NORMALIZATION REPORT")
    lines.append("")
    lines.append("Materials:")
    lines.append(
        "  before normalization: "
        f"mentions={sum(stats['raw_material_counts'].values())}, "
        f"unique_raw={len(stats['raw_material_counts'])}"
    )
    lines.append(
        "  after normalization: "
        f"mentions={sum(stats['material_counts'].values())}, "
        f"unique_canonical={len(stats['material_counts'])}"
    )
    lines.append("")
    lines.append("Processes:")
    lines.append(
        "  before normalization: "
        f"mentions={sum(stats['raw_process_counts'].values())}, "
        f"unique_raw={len(stats['raw_process_counts'])}"
    )
    lines.append(
        "  after normalization: "
        f"mentions={sum(stats['process_counts'].values())}, "
        f"unique_canonical={len(stats['process_counts'])}"
    )

    lines.append("")
    lines.append("Top-30 normalization merges:")
    rows = merge_rows("Material", stats["material_alias_counts"])
    rows.extend(merge_rows("Process", stats["process_alias_counts"]))
    rows.sort(key=lambda item: (-item[0], item[1], item[2]))
    if not rows:
        lines.append("  no merges")
    for total, entity_type, canonical, aliases in rows[:30]:
        alias_text = ", ".join(
            f"{alias}({count})"
            for alias, count in aliases.most_common()
        )
        lines.append(f"  {entity_type} {canonical} <- {alias_text} | total={total}")

    lines.append("")
    lines.append("Process base groups:")
    groups = process_base_groups(
        stats["process_counts"],
        stats["process_base_variant_by_name"],
    )
    for base in sorted(groups):
        variants = ", ".join(
            f"{variant}({count})"
            for variant, count in groups[base].most_common()
        )
        lines.append(f"  {base} -> {variants}")

    lines.append("")
    lines.append("Подозрения на дубли:")
    duplicate_rows = duplicate_suspicions("Material", stats["material_counts"])
    duplicate_rows.extend(duplicate_suspicions("Process", stats["process_counts"]))
    duplicate_rows.sort()
    if not duplicate_rows:
        lines.append("  no suspicious duplicates")
    for _, entity_type, words, left_name, left_count, right_name, right_count in duplicate_rows:
        lines.append(
            f"  {entity_type}: {left_name}({left_count}) <-> "
            f"{right_name}({right_count}) | words={words}"
        )

    lines.append("")
    lines.append("Node counts by node_type:")
    for node_type, count in sorted(node_counts.items()):
        lines.append(f"  {node_type}: {count}")

    lines.append("")
    lines.append("Edge counts by edge_type:")
    for edge_type, count in sorted(edge_counts.items()):
        lines.append(f"  {edge_type}: {count}")

    lines.append("")
    lines.append("Metadata coverage on yields edges:")
    lines.append(f"  with_year: {sum(1 for edge in yields_edges if edge.get('year') is not None)}")
    lines.append(f"  with_location_geo: {sum(1 for edge in yields_edges if edge.get('location_geo'))}")
    lines.append(f"  with_lab_or_author: {sum(1 for edge in yields_edges if edge.get('lab_or_author'))}")
    lines.append(f"  with_equipment: {sum(1 for edge in yields_edges if edge.get('equipment'))}")
    lines.append(f"  with_conditions: {sum(1 for edge in yields_edges if edge.get('conditions'))}")

    lines.append("")
    lines.append("Input record counts:")
    for record_type, count in sorted(stats["record_type_counts"].items(), key=lambda item: str(item[0])):
        lines.append(f"  {record_type}: {count}")

    lines.append("")
    lines.append("Skipped counts:")
    if stats["skipped_counts"]:
        for reason, count in sorted(stats["skipped_counts"].items()):
            lines.append(f"  {reason}: {count}")
    else:
        lines.append("  none")

    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Normalization report saved: {path}")
    except Exception as exc:
        print(f"ERROR: cannot write normalization report {path} -> {exc}")


def write_graph(path, graph):
    try:
        try:
            data = json_graph.node_link_data(graph, edges="links")
        except TypeError:
            data = json_graph.node_link_data(graph)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Graph saved: {path}")
    except Exception as exc:
        print(f"ERROR: cannot write graph JSON {path} -> {exc}")


def print_summary(graph):
    node_counts = node_type_counts(graph)
    edge_counts = edge_type_counts(graph)
    document_count = node_counts.get("Document", 0)

    print("")
    print("Done.")
    print("Nodes by type:")
    for node_type, count in sorted(node_counts.items()):
        print(f"  {node_type}: {count}")
    print(f"Edges total: {graph.number_of_edges()}")
    print("Edges by type:")
    for edge_type, count in sorted(edge_counts.items()):
        print(f"  {edge_type}: {count}")
    print(f"Documents: {document_count}")


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report)
    synonyms_path = Path(args.synonyms)

    print(f"Input: {input_path}")
    print(f"Output graph: {output_path}")
    print(f"Report: {report_path}")
    print(f"Synonyms: {synonyms_path}")

    ensure_synonyms_file(synonyms_path)

    if nx is None:
        print("")
        print("ERROR: networkx is not installed or cannot be imported.")
        print(f"Import error: {NETWORKX_IMPORT_ERROR}")
        print("Install dependency: pip install networkx")
        return

    synonym_map = load_synonym_map(synonyms_path)

    if not input_path.exists():
        print(f"ERROR: input file does not exist: {input_path}")
        return

    print("")
    print("Reading JSONL records...")
    records, read_stats = read_jsonl_records(input_path)
    print(
        "Read summary: "
        f"lines={read_stats['lines']}, records={read_stats['records']}, "
        f"bad_json={read_stats['bad_json']}, bad_record={read_stats['bad_record']}"
    )
    if not records:
        print("WARNING: no records to process")
        return

    print("")
    print("Building graph...")
    graph, stats = build_graph(records, synonym_map)
    graph.graph["source"] = str(input_path)

    print("")
    print("Writing outputs...")
    write_graph(output_path, graph)
    write_report(report_path, graph, stats)
    print_summary(graph)


if __name__ == "__main__":
    main()
