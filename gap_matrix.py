import argparse
import html
import math
from collections import Counter, defaultdict
from pathlib import Path

try:
    import pandas as pd
except Exception as exc:
    pd = None
    PANDAS_IMPORT_ERROR = exc
else:
    PANDAS_IMPORT_ERROR = None

try:
    import plotly.graph_objects as go
except Exception as exc:
    go = None
    PLOTLY_IMPORT_ERROR = exc
else:
    PLOTLY_IMPORT_ERROR = None

from query_graph import (
    GRAPH_PATH,
    clean_text,
    iter_fact_rows,
    load_graph,
    node_label,
    parse_number_range,
)


AXIS_TYPES = {
    "material": "Material",
    "materials": "Material",
    "process": "Process",
    "processes": "Process",
    "property": "Property",
    "properties": "Property",
    "result": "Property",
    "result_property": "Property",
}

AXIS_TITLE_WORDS = {
    "material": "материалов",
    "materials": "материалов",
    "process": "процессов",
    "processes": "процессов",
    "property": "свойств",
    "properties": "свойств",
    "result": "свойств",
    "result_property": "свойств",
}

AXIS_DISPLAY_NAMES = {
    "material": "материал",
    "materials": "материал",
    "process": "процесс",
    "processes": "процесс",
    "property": "показатель",
    "properties": "показатель",
    "result": "показатель",
    "result_property": "показатель",
}


BASE_LABEL_ALIASES = {
    "никеля": "никель",
    "концентраты": "концентрат",
    "концентрата": "концентрат",
    "воды": "вода",
    "шлаки": "шлак",
    "шлака": "шлак",
    "сплавы": "сплав",
    "сплава": "сплав",
    "растворы": "раствор",
    "раствора": "раствор",
    "штейны": "штейн",
    "штейна": "штейн",
    "руды": "руда",
    "файнштейна": "файнштейн",
    "сульфиды": "сульфид",
    "частицы": "частица",
    "латериты": "латерит",
}

MATERIAL_NAME_LABELS = {
    "шлак медеплавильного производства": "медеплавильный шлак",
    "шлаки медеплавильного производства": "медеплавильный шлак",
    "сырье для доменного производства": "доменное сырье",
    "сырьё для доменного производства": "доменное сырье",
}

LEACHING_MATERIAL_LABELS = [
    ("раствор", "раствор"),
    ("остаток", "остаток"),
    ("фильтрат", "фильтрат"),
    ("кек", "кек"),
    ("осадок", "осадок"),
    ("щелок", "щелок"),
    ("пульпа", "пульпа"),
    ("фаза", "твердая фаза"),
]


def display_label_override(data):
    node_type = data.get("node_type")
    if node_type != "Material":
        return None

    name = clean_text(data.get("name") or data.get("display_name"))
    if name in MATERIAL_NAME_LABELS:
        return MATERIAL_NAME_LABELS[name]

    base = clean_text(data.get("base"))
    if base == "производства":
        if "шлак" in name:
            return "медеплавильный шлак"
        if "сырье" in name or "сырьё" in name:
            return "доменное сырье"

    if base == "выщелачивания":
        for needle, label in LEACHING_MATERIAL_LABELS:
            if needle in name:
                return label

    return None


def require_pandas():
    if pd is None:
        print("")
        print("ERROR: pandas is not installed or cannot be imported.")
        print(f"Import error: {PANDAS_IMPORT_ERROR}")
        print("Install dependency: pip install pandas")
        return False
    return True


def require_plotly():
    if go is None:
        print("")
        print("ERROR: plotly is not installed or cannot be imported.")
        print(f"Import error: {PLOTLY_IMPORT_ERROR}")
        print("Install dependency: pip install plotly")
        return False
    return True


def normalize_axis(axis):
    key = clean_text(axis)
    if key not in AXIS_TYPES:
        allowed = ", ".join(sorted(AXIS_TYPES))
        print(f"ERROR: unknown axis '{axis}'. Allowed values: {allowed}")
        return None
    return AXIS_TYPES[key]


def axis_node(axis_type, material_data, process_data, property_data):
    if axis_type == "Material":
        return material_data
    if axis_type == "Process":
        return process_data
    if axis_type == "Property":
        return property_data
    return {}


def axis_label(data, detail=False):
    if not data:
        return None

    if not detail:
        override = display_label_override(data)
        if override:
            return override

        base = data.get("base")
        if base:
            base_key = clean_text(base)
            return BASE_LABEL_ALIASES.get(base_key, str(base))

    label = node_label(data)
    if label:
        return str(label)

    return None


def format_number(value):
    if value is None:
        return "?"
    if abs(value) >= 100:
        return f"{value:.0f}"
    return f"{value:.3g}"


def most_common_unit(points):
    counter = Counter()
    for point in points:
        unit = point.get("unit")
        if unit:
            counter[str(unit)] += 1
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def bucket_count(value_count):
    if value_count <= 1:
        return 1
    return min(8, max(5, int(round(math.sqrt(value_count)))))


def make_buckets(points):
    if not points:
        return []

    values = [point["mid"] for point in points]
    min_value = min(values)
    max_value = max(values)
    unit = most_common_unit(points)

    if min_value == max_value:
        label = format_number(min_value)
        if unit:
            label = f"{label} {unit}"
        return [{"start": min_value, "end": max_value, "label": label}]

    count = bucket_count(len(values))
    width = (max_value - min_value) / count
    buckets = []

    for index in range(count):
        start = min_value + width * index
        end = max_value if index == count - 1 else min_value + width * (index + 1)
        label = f"{format_number(start)}-{format_number(end)}"
        if unit:
            label = f"{label} {unit}"
        buckets.append({"start": start, "end": end, "label": label})

    return buckets


def find_bucket_label(value, buckets):
    for index, bucket in enumerate(buckets):
        start = bucket["start"]
        end = bucket["end"]
        if index == len(buckets) - 1:
            if start <= value <= end:
                return bucket["label"]
        elif start <= value < end:
            return bucket["label"]
    return None


def matching_condition_points(fact, condition_parameter):
    points = []
    parameter = clean_text(condition_parameter)
    conditions = fact.get("conditions")
    if not isinstance(conditions, list):
        return points

    for condition in conditions:
        if not isinstance(condition, dict):
            continue

        condition_name = clean_text(condition.get("parameter"))
        if parameter not in condition_name:
            continue

        value_range = parse_number_range(condition.get("value"))
        if value_range is None:
            continue

        value_min, value_max = value_range
        points.append(
            {
                "min": value_min,
                "max": value_max,
                "mid": (value_min + value_max) / 2,
                "unit": condition.get("unit"),
                "condition": condition,
            }
        )

    return points


def example_text(fact):
    source_file = fact.get("source_file") or "unknown source"
    quote = fact.get("source_quote") or ""
    if quote:
        return f"{source_file}: {quote}"
    return str(source_file)


def add_example(examples, row_label, column_label, fact, max_examples=3):
    key = (row_label, column_label)
    text = example_text(fact)
    if text in examples[key]:
        return
    if len(examples[key]) < max_examples:
        examples[key].append(text)


def fact_key(fact):
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


def top_labels(records, field, top_n, min_mentions):
    counts = Counter()
    seen = set()

    for record in records:
        label = record.get(field)
        if label is None:
            continue

        key = (field, label, fact_key(record["fact"]))
        if key in seen:
            continue
        seen.add(key)
        counts[label] += 1

    labels = [
        label
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= min_mentions
    ]

    if top_n is not None and top_n > 0:
        labels = labels[:top_n]

    return labels, counts


def filter_records(records, row_labels, column_labels=None):
    row_set = set(row_labels)
    column_set = set(column_labels) if column_labels is not None else None
    filtered = []

    for record in records:
        if record.get("row") not in row_set:
            continue
        if column_set is not None and record.get("column") not in column_set:
            continue
        filtered.append(record)

    return filtered


def axis_title_word(axis):
    return AXIS_TITLE_WORDS.get(clean_text(axis), str(axis))


def axis_title_part(axis, top_n):
    return f"топ-{top_n} {axis_title_word(axis)}"


def matrix_title(axis1, axis2, condition_parameter, top_n_axis1, top_n_axis2):
    first = axis_title_part(axis1, top_n_axis1)
    if condition_parameter:
        second = f'бакеты "{condition_parameter}"'
    else:
        second = axis_title_part(axis2, top_n_axis2)
    return f"{first} × {second} по частоте упоминаний"


def axis_display_name(axis):
    return AXIS_DISPLAY_NAMES.get(clean_text(axis), str(axis))


def build_fact_records(graph, axis1_type, axis2_type, condition_parameter, detail):
    records = []
    condition_points = []

    for fact, material_data, process_data, property_data in iter_fact_rows(graph):
        row_data = axis_node(axis1_type, material_data, process_data, property_data)
        row_label = axis_label(row_data, detail=detail)
        if row_label is None:
            continue

        if condition_parameter:
            points = matching_condition_points(fact, condition_parameter)
            for point in points:
                condition_points.append(point)
                records.append({"row": row_label, "point": point, "fact": fact})
            continue

        column_data = axis_node(axis2_type, material_data, process_data, property_data)
        column_label = axis_label(column_data, detail=detail)
        if column_label is None:
            continue

        records.append({"row": row_label, "column": column_label, "fact": fact})

    return records, condition_points


def empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1=18, top_n_axis2=12, min_mentions=3):
    df = pd.DataFrame()
    df.attrs["axis1"] = axis1
    df.attrs["axis2"] = condition_parameter or axis2
    df.attrs["axis2_kind"] = "condition_bucket" if condition_parameter else "entity"
    df.attrs["condition_parameter"] = condition_parameter
    df.attrs["detail"] = detail
    df.attrs["examples"] = {}
    df.attrs["top_n_axis1"] = top_n_axis1
    df.attrs["top_n_axis2"] = top_n_axis2
    df.attrs["min_mentions"] = min_mentions
    df.attrs["row_counts"] = {}
    df.attrs["column_counts"] = {}
    df.attrs["title"] = matrix_title(axis1, axis2, condition_parameter, top_n_axis1, top_n_axis2)
    return df


def build_matrix(
    axis1="material",
    axis2="process",
    condition_parameter=None,
    detail=False,
    graph_path=GRAPH_PATH,
    top_n_axis1=18,
    top_n_axis2=12,
    min_mentions=3,
):
    if not require_pandas():
        return None

    axis1_type = normalize_axis(axis1)
    axis2_type = normalize_axis(axis2)
    if axis1_type is None or axis2_type is None:
        return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)

    graph = load_graph(graph_path)
    if graph is None:
        return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)

    print(
        "Building gap matrix: "
        f"axis1={axis1}, axis2={axis2}, "
        f"condition_parameter={condition_parameter}, detail={detail}, "
        f"top_n_axis1={top_n_axis1}, top_n_axis2={top_n_axis2}, min_mentions={min_mentions}"
    )

    records, condition_points = build_fact_records(
        graph,
        axis1_type,
        axis2_type,
        condition_parameter,
        detail,
    )

    if not records:
        print("WARNING: no facts matched matrix axes")
        return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)

    rows, raw_row_counts = top_labels(records, "row", top_n_axis1, min_mentions)
    if not rows:
        print("WARNING: no axis1 labels passed top/min_mentions filter")
        return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)

    records = filter_records(records, rows)

    buckets = []
    if condition_parameter:
        condition_points = [record["point"] for record in records]
        buckets = make_buckets(condition_points)
        if not buckets:
            print(f"WARNING: no numeric condition values found for '{condition_parameter}'")
            return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)

        for record in records:
            record["column"] = find_bucket_label(record["point"]["mid"], buckets)
        records = [record for record in records if record.get("column") is not None]
        columns = [bucket["label"] for bucket in buckets]
        raw_column_counts = Counter(record["column"] for record in records)
    else:
        columns, raw_column_counts = top_labels(records, "column", top_n_axis2, min_mentions)
        if not columns:
            print("WARNING: no axis2 labels passed top/min_mentions filter")
            return empty_matrix(axis1, axis2, condition_parameter, detail, top_n_axis1, top_n_axis2, min_mentions)
        records = filter_records(records, rows, columns)

    counts = Counter()
    row_counts = Counter()
    column_counts = Counter()
    examples = defaultdict(list)

    for record in records:
        row_label = record["row"]
        column_label = record["column"]
        fact = record["fact"]

        counts[(row_label, column_label)] += 1
        row_counts[row_label] += 1
        column_counts[column_label] += 1
        add_example(examples, row_label, column_label, fact)

    rows = [row_label for row_label in rows if row_label in row_counts]
    columns = [column_label for column_label in columns if column_label in column_counts]

    matrix = []
    for row_label in rows:
        matrix.append([counts.get((row_label, column_label), 0) for column_label in columns])

    df = pd.DataFrame(matrix, index=rows, columns=columns, dtype=int)
    df.attrs["axis1"] = axis1
    df.attrs["axis2"] = condition_parameter or axis2
    df.attrs["axis2_kind"] = "condition_bucket" if condition_parameter else "entity"
    df.attrs["condition_parameter"] = condition_parameter
    df.attrs["detail"] = detail
    df.attrs["examples"] = dict(examples)
    df.attrs["row_counts"] = dict(row_counts)
    df.attrs["column_counts"] = dict(column_counts)
    df.attrs["raw_row_counts"] = dict(raw_row_counts)
    df.attrs["raw_column_counts"] = dict(raw_column_counts)
    df.attrs["top_n_axis1"] = top_n_axis1
    df.attrs["top_n_axis2"] = top_n_axis2
    df.attrs["min_mentions"] = min_mentions
    df.attrs["buckets"] = buckets
    df.attrs["title"] = matrix_title(axis1, axis2, condition_parameter, top_n_axis1, top_n_axis2)

    print(f"Matrix built: rows={len(rows)}, columns={len(columns)}, facts={sum(counts.values())}")
    return df


def hover_examples(df, row_label, column_label):
    examples = df.attrs.get("examples", {})
    values = examples.get((row_label, column_label), [])
    if not values:
        return "empty cell"
    return "<br>".join(values)


def render(df):
    if df is None:
        print("ERROR: cannot render empty DataFrame object")
        return None
    if not require_plotly():
        return None

    axis1 = df.attrs.get("axis1", "axis1")
    axis2 = df.attrs.get("axis2", "axis2")
    axis1_display = axis_display_name(axis1)
    axis2_display = axis_display_name(axis2)
    condition_parameter = df.attrs.get("condition_parameter")
    if condition_parameter:
        axis2_display = str(condition_parameter)

    z = df.values.tolist()
    customdata = []
    for row_label in df.index:
        row = []
        for column_label in df.columns:
            row.append(hover_examples(df, row_label, column_label))
        customdata.append(row)

    max_value = 1
    if len(df.index) > 0 and len(df.columns) > 0:
        max_value = max(1, int(df.values.max()))

    title = df.attrs.get("title") or f"Gap matrix: {axis1} x {axis2}"

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=list(df.columns),
            y=list(df.index),
            customdata=customdata,
            colorscale=[
                [0.0, "#111827"],
                [0.0001, "#111827"],
                [0.0002, "#1e3a5f"],
                [0.45, "#2563eb"],
                [1.0, "#22d3ee"],
            ],
            zmin=0,
            zmax=max_value,
            colorbar={
                "title": {"text": "фактов"},
                "thickness": 12,
                "len": 0.72,
                "outlinewidth": 0,
                "tickfont": {"size": 11, "color": "#cbd5e1"},
            },
            hovertemplate=(
                axis1_display
                + ": %{y}<br>"
                + axis2_display
                + ": %{x}<br>"
                + "facts: %{z}<br>"
                + "%{customdata}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title={"text": title, "x": 0.0, "xanchor": "left", "font": {"size": 15}},
        xaxis_title=None,
        yaxis_title=None,
        template="plotly_dark",
        height=max(460, min(820, 180 + len(df.index) * 24)),
        margin={"l": 145, "r": 70, "t": 64, "b": 125},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0f172a",
        font={"color": "#e5e7eb", "size": 12},
    )
    fig.update_xaxes(
        side="bottom",
        tickangle=-35,
        automargin=True,
        tickfont={"size": 11, "color": "#e5e7eb"},
        showgrid=False,
        zeroline=False,
    )
    fig.update_yaxes(
        automargin=True,
        tickfont={"size": 11, "color": "#e5e7eb"},
        showgrid=False,
        zeroline=False,
    )
    return fig


def gaps(df):
    if df is None:
        return []

    rows = []
    values = df.to_numpy()
    row_labels = list(df.index)
    column_labels = list(df.columns)
    row_totals = df.sum(axis=1).to_numpy()
    column_totals = df.sum(axis=0).to_numpy()
    axis1 = df.attrs.get("axis1", "axis1")
    axis2 = df.attrs.get("axis2", "axis2")

    for row_index, row_label in enumerate(row_labels):
        for column_index, column_label in enumerate(column_labels):
            value = int(values[row_index][column_index])
            if value != 0:
                continue

            row_total = int(row_totals[row_index])
            column_total = int(column_totals[column_index])
            interest = row_total * column_total
            rows.append(
                {
                    axis1: row_label,
                    axis2: column_label,
                    "interest": interest,
                    "axis1_total": row_total,
                    "axis2_total": column_total,
                }
            )

    rows.sort(key=lambda item: (-item["interest"], -item["axis1_total"], -item["axis2_total"]))
    return rows


def parse_args():
    parser = argparse.ArgumentParser(description="Build gap heatmap from graph.json")
    parser.add_argument("--axis1", default="material", help='First axis (default: "material")')
    parser.add_argument("--axis2", default="process", help='Second axis (default: "process")')
    parser.add_argument(
        "--condition-parameter",
        default=None,
        help='Use numeric buckets of this condition as second axis, for example "temperature"',
    )
    parser.add_argument("--detail", action="store_true", help="Use full entity names instead of base fields")
    parser.add_argument("--graph", default=str(GRAPH_PATH), help='Graph JSON path (default: "graph.json")')
    parser.add_argument("--output", default="matrix.html", help='Output HTML path (default: "matrix.html")')
    parser.add_argument("--top1", type=int, default=18, help="Top N labels for first axis")
    parser.add_argument("--top2", type=int, default=12, help="Top N labels for second axis")
    parser.add_argument("--min-mentions", type=int, default=3, help="Minimum fact mentions for axis labels")
    parser.add_argument("--top-gaps", type=int, default=10, help="Print this many top gaps")
    return parser.parse_args()


def main():
    args = parse_args()
    df = build_matrix(
        axis1=args.axis1,
        axis2=args.axis2,
        condition_parameter=args.condition_parameter,
        detail=args.detail,
        graph_path=Path(args.graph),
        top_n_axis1=args.top1,
        top_n_axis2=args.top2,
        min_mentions=args.min_mentions,
    )
    if df is None:
        return

    gap_rows = gaps(df)
    print(f"Empty cells: {len(gap_rows)}")
    for item in gap_rows[: args.top_gaps]:
        print(
            "  "
            f"{item.get(df.attrs.get('axis1'))} x {item.get(df.attrs.get('axis2'))} "
            f"| interest={item['interest']} "
            f"| totals={item['axis1_total']}x{item['axis2_total']}"
        )

    fig = render(df)
    if fig is None:
        return

    output_path = Path(args.output)
    title = df.attrs.get("title") or "Gap matrix"
    try:
        plot_html = fig.to_html(full_html=False, include_plotlyjs=True)
        page_html = (
            "<!doctype html>\n"
            "<html>\n"
            "<head>\n"
            '  <meta charset="utf-8">\n'
            f"  <title>{html.escape(title)}</title>\n"
            "</head>\n"
            "<body>\n"
            f"  <h1>{html.escape(title)}</h1>\n"
            f"{plot_html}\n"
            "</body>\n"
            "</html>\n"
        )
        output_path.write_text(page_html, encoding="utf-8")
        print(f"Matrix HTML saved: {output_path}")
    except Exception as exc:
        print(f"ERROR: cannot write matrix HTML {output_path} -> {exc}")


if __name__ == "__main__":
    main()
