import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps
} from "@xyflow/react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  Database,
  Download,
  FileText,
  FlaskConical,
  Globe2,
  LayoutGrid,
  Loader2,
  Network,
  Route,
  ScanSearch,
  Search,
  ShieldCheck,
  Sparkles,
  Users
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

type Counts = {
  nodes: number;
  links: number;
  documents: number;
  facts: number;
  materials: number;
  processes: number;
  properties: number;
  experts: number;
  equipment: number;
  demoDocuments: number;
  preparedTxt: number;
};

type Preset = {
  label: string;
  query: string;
  status: string;
  description: string;
  filters: Record<string, unknown>;
};

type Dashboard = {
  graph: {
    updatedAt?: string;
    verificationStatus?: string;
    source?: string;
  };
  counts: Counts;
  confidence: Array<{ key: string; label: string; value: number }>;
  topEntities: Record<string, Array<{ id: string; name: string; mentions: number; type: string }>>;
  presets: Preset[];
};

type Fact = {
  material?: string;
  process?: string;
  result_property?: string;
  result_value?: string | number;
  result_unit?: string;
  direction?: string;
  conditions?: Array<{ parameter?: string; value?: string; unit?: string }>;
  source_file?: string;
  source_quote?: string;
  confidence?: string;
  year?: string | number;
  location_geo?: string;
  geo_scope?: string;
  lab_or_author?: string;
  equipment?: string;
};

type Method = {
  process?: string;
  facts?: number;
  documents?: number;
  top_materials?: string;
  top_results?: string;
  representative_source?: string;
  representative_quote?: string;
};

type Expert = {
  expert?: string;
  facts?: number;
  documents?: number;
  top_sources?: string;
};

type GeoRow = {
  location_geo?: string;
  facts?: number;
  documents?: number;
  year_range?: string;
};

type Conflict = {
  material?: string;
  process?: string;
  result_property?: string;
  values?: string[];
  directions?: string[];
  facts?: number;
  sources?: string[];
  status?: string;
  example_quote?: string;
};

type Answer = {
  title: string;
  summary: string;
  metrics: Record<string, number | string>;
  methods: Method[];
  evidence_rows: Fact[];
  experts: Expert[];
  geo_breakdown: GeoRow[];
  potential_conflicts: Conflict[];
  gaps: Array<{ gap: string; detail: string }>;
  markdown: string;
};

type QueryResponse = {
  query: string;
  filters: Record<string, unknown>;
  facts: Fact[];
  answer: Answer;
};

type MatrixCell = {
  row: string;
  column: string;
  count: number;
  state: "empty" | "single" | "partial" | "covered";
  stateLabel: string;
  examples?: string[];
  axis1?: string;
  axis2?: string;
  condition_parameter?: string | null;
};

type MatrixResponse = {
  axis1: string;
  axis2: string;
  condition_parameter?: string | null;
  axisLabels: { axis1: string; axis2: string };
  rows: string[];
  columns: string[];
  cells: MatrixCell[];
  gaps: Array<MatrixCell & { interest: number; rowTotal: number; columnTotal: number }>;
};

type GraphPayload = {
  nodes: Array<{ id: string; label: string; kind: string }>;
  edges: Array<{ id: string; source: string; target: string; label: string }>;
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options
  });
  if (!response.ok) {
    throw new Error(`${response.status}: ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}

function formatNumber(value?: number | string) {
  const numeric = Number(value ?? 0);
  return new Intl.NumberFormat("ru-RU").format(Number.isFinite(numeric) ? numeric : 0);
}

function confidenceLabel(value?: string) {
  const key = String(value || "unknown").toLowerCase();
  if (key === "high") return "Высокая";
  if (key === "medium") return "Средняя";
  if (key === "low") return "Низкая";
  return "Не указана";
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function factResult(fact: Fact) {
  const value = [fact.result_value, fact.result_unit].filter(Boolean).join(" ");
  return [fact.result_property, value].filter(Boolean).join(": ") || "Результат не указан";
}

function conditionsText(fact: Fact) {
  if (!Array.isArray(fact.conditions) || fact.conditions.length === 0) return "Условия в источнике не распознаны";
  return fact.conditions
    .slice(0, 3)
    .map((condition) => [condition.parameter, condition.value, condition.unit].filter(Boolean).join(" "))
    .join("; ");
}

function factQueryTarget(fact: Fact) {
  return [fact.material, fact.process, fact.result_property].filter(Boolean).join(" ");
}

function relatedReason(fact: Fact) {
  const anchors = [
    fact.material && `материал: ${fact.material}`,
    fact.process && `процесс: ${fact.process}`,
    fact.result_property && `показатель: ${fact.result_property}`
  ].filter(Boolean);
  if (anchors.length === 0) return "Факт входит в текущую выборку ответа и требует проверки по источнику.";
  return `Связан с ответом через ${anchors.slice(0, 2).join(" · ")}.`;
}

function factMeta(fact: Fact) {
  return [fact.year && `${fact.year}`, fact.location_geo, fact.lab_or_author].filter(Boolean).slice(0, 3);
}

function cellContext(cell: MatrixCell, matrix: MatrixResponse): MatrixCell {
  return {
    ...cell,
    axis1: matrix.axis1,
    axis2: matrix.axis2,
    condition_parameter: matrix.condition_parameter ?? null
  };
}

const KIND_LABELS: Record<string, string> = {
  material: "Материал",
  process: "Процесс",
  property: "Показатель",
  document: "Источник",
  expert: "Эксперт",
  gap: "Пробел",
  fact: "Факт"
};

// Порядок колонок слева-направо: цепочка «эксперт → материал → процесс → показатель → источник».
const COLUMN_ORDER = ["expert", "material", "process", "property", "document", "gap", "fact"];

type EntityNodeData = { label: string; kind: string };

function EntityNode({ data }: NodeProps) {
  const nodeData = data as EntityNodeData;
  return (
    <div className={`gnode gnode-${nodeData.kind}`} title={nodeData.label}>
      <Handle type="target" position={Position.Left} className="gnode-handle" />
      <span className="gnode-kind">{KIND_LABELS[nodeData.kind] ?? nodeData.kind}</span>
      <span className="gnode-label">{nodeData.label}</span>
      <Handle type="source" position={Position.Right} className="gnode-handle" />
    </div>
  );
}

const nodeTypes = { entity: EntityNode };

function flowLayout(payload?: GraphPayload) {
  if (!payload || payload.nodes.length === 0) return { nodes: [], edges: [] };

  const colGap = 250;
  const rowGap = 92;

  // Группируем узлы по типу с сохранением порядка появления.
  const byKind = new Map<string, GraphPayload["nodes"]>();
  payload.nodes.forEach((node) => {
    const bucket = byKind.get(node.kind) ?? [];
    bucket.push(node);
    byKind.set(node.kind, bucket);
  });

  // Оставляем только реально присутствующие колонки, чтобы граф был компактным.
  const usedColumns = COLUMN_ORDER.filter((kind) => byKind.has(kind));
  const extraKinds = [...byKind.keys()].filter((kind) => !COLUMN_ORDER.includes(kind));
  const columns = [...usedColumns, ...extraKinds];

  const nodes: Node[] = [];
  columns.forEach((kind, columnIndex) => {
    const bucket = byKind.get(kind) ?? [];
    bucket.forEach((node, rowIndex) => {
      const columnHeight = (bucket.length - 1) * rowGap;
      nodes.push({
        id: node.id,
        type: "entity",
        data: { label: node.label, kind: node.kind },
        position: {
          x: columnIndex * colGap,
          y: rowIndex * rowGap - columnHeight / 2
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left
      });
    });
  });

  const edges: Edge[] = payload.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    type: "smoothstep",
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, color: "#93a2ba", width: 16, height: 16 },
    style: { stroke: "#b7c3d6", strokeWidth: 1.5 },
    labelStyle: { fill: "#5b6a80", fontSize: 10, fontWeight: 700 },
    labelBgStyle: { fill: "#ffffff", fillOpacity: 0.9 },
    labelBgPadding: [4, 2] as [number, number],
    labelBgBorderRadius: 4
  }));

  return { nodes, edges };
}

const VIEWS = [
  {
    id: "overview",
    label: "Обзор",
    icon: Sparkles,
    title: "Проверяемый ответ",
    subtitle: "Задайте R&D-запрос, затем проверьте вывод, факты, источники и пробелы"
  },
  {
    id: "graph",
    label: "Граф знаний",
    icon: Network,
    title: "Граф знаний",
    subtitle: "Цепочки «материал → процесс → показатель → источник»"
  },
  {
    id: "matrix",
    label: "Матрица пробелов",
    icon: LayoutGrid,
    title: "Матрица пробелов",
    subtitle: "Что уже покрыто источниками, а где планировать исследование"
  },
  {
    id: "insights",
    label: "Гео и противоречия",
    icon: ScanSearch,
    title: "Гео и противоречия",
    subtitle: "География практики, расхождения выводов и группировка методов"
  },
  {
    id: "evidence",
    label: "Источники",
    icon: FileText,
    title: "Источники и доказательства",
    subtitle: "Цитаты, уровень достоверности и кандидаты на исследование"
  },
  {
    id: "entities",
    label: "Сущности",
    icon: Boxes,
    title: "Сущности графа",
    subtitle: "Топ материалов, процессов, показателей, авторов и организаций"
  }
] as const;

type ViewId = (typeof VIEWS)[number]["id"];

const ENTITY_META: Record<string, { label: string; icon: typeof Boxes }> = {
  materials: { label: "Материалы", icon: Boxes },
  processes: { label: "Процессы", icon: Route },
  properties: { label: "Показатели", icon: LayoutGrid },
  experts: { label: "Авторы и организации", icon: Users }
};

const MATRIX_LEGEND = [
  { className: "empty", label: "не исследовано", range: "0" },
  { className: "single", label: "единичные данные", range: "1-2" },
  { className: "partial", label: "частично изучено", range: "3-5" },
  { className: "covered", label: "изучено много", range: "6+" }
];

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [graph, setGraph] = useState<GraphPayload | undefined>();
  const [searchValue, setSearchValue] = useState("");
  const [activePreset, setActivePreset] = useState("");
  const [selectedCell, setSelectedCell] = useState<MatrixCell | null>(null);
  const [selectedGraphNode, setSelectedGraphNode] = useState<EntityNodeData | null>(null);
  const [axis1, setAxis1] = useState("material");
  const [axis2, setAxis2] = useState("process");
  const [condition, setCondition] = useState("");
  const [top1, setTop1] = useState(15);
  const [top2, setTop2] = useState(10);
  const [loading, setLoading] = useState(true);
  const [queryLoading, setQueryLoading] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<ViewId>("overview");
  const workspaceRef = useRef<HTMLElement | null>(null);

  async function loadDashboard() {
    const data = await api<Dashboard>("/api/dashboard");
    setDashboard(data);
    return data;
  }

  async function loadMatrix() {
    const params = new URLSearchParams({
      axis1,
      axis2,
      top1: String(top1),
      top2: String(top2),
      min_mentions: "3"
    });
    if (condition) params.set("condition_parameter", condition);
    const data = await api<MatrixResponse>(`/api/matrix?${params.toString()}`);
    setMatrix(data);
    return data;
  }

  async function refreshQuery(query: string, filters: Record<string, unknown> = {}, matrixCell?: MatrixCell | null) {
    setQueryLoading(true);
    setError("");
    try {
      const result = await api<QueryResponse>("/api/query", {
        method: "POST",
        body: JSON.stringify({ query, filters, matrixCell })
      });
      setQueryResult(result);
      const graphResult = await api<GraphPayload>("/api/subgraph", {
        method: "POST",
        body: JSON.stringify({ facts: result.facts.slice(0, 10), matrixCell, limit: 10 })
      });
      setGraph(graphResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setQueryLoading(false);
    }
  }

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    Promise.all([loadDashboard(), loadMatrix()])
      .then(([dash]) => {
        if (!mounted) return;
        const preset = dash.presets[0];
        setActivePreset(preset.label);
        setSearchValue(preset.query);
        void refreshQuery(preset.query, preset.filters);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    void loadMatrix().catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [axis1, axis2, condition, top1, top2]);

  const matrixLookup = useMemo(() => {
    const lookup = new Map<string, MatrixCell>();
    matrix?.cells.forEach((cell) => lookup.set(`${cell.row}///${cell.column}`, cell));
    return lookup;
  }, [matrix]);

  const flow = useMemo(() => flowLayout(graph), [graph]);

  const confidencePercent = useMemo(() => {
    const metrics = queryResult?.answer.metrics;
    const high = Number(metrics?.high_confidence ?? 0);
    const medium = Number(metrics?.medium_confidence ?? 0);
    const low = Number(metrics?.low_confidence ?? 0);
    const unknown = Number(metrics?.unknown_confidence ?? 0);
    const total = high + medium + low + unknown;
    if (!total) return 0;
    return Math.round(((high + medium * 0.65 + low * 0.35) / total) * 100);
  }, [queryResult]);

  const confidenceCounts = useMemo(() => {
    const metrics = queryResult?.answer.metrics;
    const high = Number(metrics?.high_confidence ?? 0);
    const medium = Number(metrics?.medium_confidence ?? 0);
    const low = Number(metrics?.low_confidence ?? 0);
    const unknown = Number(metrics?.unknown_confidence ?? 0);
    return { high, medium, low, unknown, total: high + medium + low + unknown };
  }, [queryResult]);

  const statItems = useMemo(() => {
    const counts = dashboard?.counts;
    return [
      { icon: Network, label: "Узлов графа", value: counts?.nodes },
      { icon: Route, label: "Связей", value: counts?.links },
      { icon: Sparkles, label: "Фактов", value: counts?.facts },
      { icon: FileText, label: "Документов", value: counts?.documents },
      { icon: Boxes, label: "Материалов", value: counts?.materials },
      { icon: FlaskConical, label: "Процессов", value: counts?.processes },
      { icon: Users, label: "Авторов/орг.", value: counts?.experts },
      { icon: Database, label: "Оборудование", value: counts?.equipment }
    ];
  }, [dashboard]);

  function goToView(id: ViewId) {
    setView(id);
    workspaceRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function runQuery(query: string, filters: Record<string, unknown> = {}, matrixCell?: MatrixCell | null) {
    void refreshQuery(query, filters, matrixCell);
    goToView("overview");
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setSelectedCell(null);
    setSelectedGraphNode(null);
    setActivePreset("");
    runQuery(searchValue);
  }

  function runPreset(preset: Preset) {
    setActivePreset(preset.label);
    setSelectedCell(null);
    setSelectedGraphNode(null);
    setSearchValue(preset.query);
    runQuery(preset.query, preset.filters);
  }

  function selectMatrixCell(cell: MatrixCell) {
    if (!matrix) return;
    const context = cellContext(cell, matrix);
    setSelectedCell(context);
    setSelectedGraphNode(null);
    setSearchValue(`${context.row} × ${context.column}`);
    runQuery(`${context.row} × ${context.column}`, {}, context);
  }

  function downloadMarkdown() {
    if (!queryResult?.answer.markdown) return;
    const blob = new Blob([queryResult.answer.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "scientific-answer.md";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-orb">
          <Network size={40} />
        </div>
        <strong>Загружаю граф знаний и матрицу пробелов</strong>
        <span>Собираем связи материалов, процессов, показателей и источников</span>
      </div>
    );
  }

  const answer = queryResult?.answer;
  const metrics = answer?.metrics;
  const viewMeta = VIEWS.find((item) => item.id === view) ?? VIEWS[0];
  const hasAnswer = Boolean(answer);
  const isInitialQueryLoading = queryLoading && !hasAnswer;
  const searchExamples = (dashboard?.presets ?? []).slice(0, 3);
  const confidenceHelpText =
    "Индекс подтверждённости фактов: высокая достоверность считается полностью, средняя с весом 65%, низкая с весом 35%. Это не точность ИИ, а качество фактической базы ответа.";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Network size={24} />
          </div>
          <div className="brand-text">
            <span>Научный клубок</span>
            <small>R&D Knowledge Graph</small>
          </div>
        </div>

        <nav className="nav-list">
          {VIEWS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={view === item.id ? "active" : ""}
                onClick={() => goToView(item.id)}
                aria-current={view === item.id ? "page" : undefined}
              >
                <Icon size={19} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-verify">
          <div className="verify-head">
            <ShieldCheck size={16} />
            Трассируемость
          </div>
          <strong>{dashboard?.graph.verificationStatus === "auto_extracted" ? "Авто-извлечение" : dashboard?.graph.verificationStatus || "—"}</strong>
          <small>Актуализировано {formatDate(dashboard?.graph.updatedAt)}</small>
          <small>Требует экспертной проверки</small>
          <small>Источник: {dashboard?.graph.source || "—"}</small>
        </div>

        <div className="sidebar-card">
          <span>Индексировано</span>
          <strong>{formatNumber(dashboard?.counts.documents)} документа</strong>
          <small>{formatNumber(dashboard?.counts.facts)} проверяемых фактов</small>
        </div>
      </aside>

      <main className="workspace" ref={workspaceRef}>
        <header className="topbar">
          <form className="searchbar" onSubmit={submitSearch}>
            {queryLoading ? <Loader2 size={22} className="spin" /> : <Search size={22} />}
            <input
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
              aria-label="R&D запрос"
              placeholder="Введите R&D вопрос: материал, процесс, условие, география, период"
            />
            <button type="submit" disabled={queryLoading}>
              {queryLoading ? "Ищу…" : "Найти"}
            </button>
          </form>
          <div className="verify-badge">
            <ShieldCheck size={16} />
            <div>
              <strong>Трассируемо</strong>
              <span>требует экспертной проверки</span>
            </div>
          </div>
          <button
            className="export-button"
            onClick={downloadMarkdown}
            disabled={!answer?.markdown}
            title={answer?.markdown ? "Скачать текущий аналитический ответ" : "Сначала выполните запрос, чтобы появился ответ"}
          >
            <Download size={18} />
            Экспорт .md
          </button>
        </header>

        <section className="search-assist" aria-label="Подсказки для запроса">
          <p className="product-note">
            Проверяемая R&amp;D-карта знаний по документам: ответ строится из фактов, источников, графа связей и матрицы пробелов.
          </p>
          {searchExamples.length > 0 && (
            <div className="example-chips">
              <span>Можно спросить:</span>
              {searchExamples.map((preset) => (
                <button type="button" key={preset.label} onClick={() => runPreset(preset)}>
                  {preset.label}
                </button>
              ))}
            </div>
          )}
        </section>

        {error && <div className="error-banner" role="alert">{error}</div>}

        <div className="page-head">
          <div>
            <h1>{viewMeta.title}</h1>
            <p>{viewMeta.subtitle}</p>
          </div>
          {answer && (
            <div className={`query-context ${queryLoading ? "is-loading" : ""}`} title={answer.title}>
              <span>{queryLoading ? "Обновляем запрос" : "Текущий запрос"}</span>
              <strong>{answer.title || searchValue}</strong>
            </div>
          )}
        </div>

        {view === "overview" && (
          <>
            <section className="overview-grid">
              <article className={`panel answer-panel ${queryLoading ? "is-loading" : ""}`}>
                <div className="panel-title">
                  <div>
                    <Sparkles size={18} />
                    <h2>Аналитический ответ</h2>
                  </div>
                  {!isInitialQueryLoading && confidenceCounts.total > 0 && (
                    <div className="confidence-widget" title={confidenceHelpText}>
                      <div className="confidence-ring" style={{ ["--confidence" as string]: `${confidencePercent}%` }}>
                        <span>{confidencePercent}%</span>
                      </div>
                      <small>Индекс подтверждённости</small>
                    </div>
                  )}
                </div>

                {isInitialQueryLoading ? (
                  <div className="answer-loading-block" role="status">
                    <Loader2 size={24} className="spin" />
                    <strong>Собираем проверяемый ответ</strong>
                    <span>Ищем факты, цитаты, связи графа и возможные пробелы по текущему R&amp;D-запросу.</span>
                  </div>
                ) : (
                  <>
                    {queryLoading && (
                      <div className="answer-loading" role="status">
                        <Loader2 size={16} className="spin" />
                        Обновляем ответ и граф по текущему запросу
                      </div>
                    )}

                    {selectedCell && (
                      <div className="selected-cell-banner">
                        <div>
                          <span>Выбрана связка матрицы</span>
                          <strong>{selectedCell.row} × {selectedCell.column}</strong>
                          <small>{selectedCell.stateLabel} · фактов: {formatNumber(selectedCell.count)}</small>
                        </div>
                        <button type="button" onClick={() => goToView("matrix")}>Вернуться к матрице</button>
                      </div>
                    )}

                    {selectedGraphNode && (
                      <div className="selected-cell-banner graph-context">
                        <div>
                          <span>Выбран узел графа</span>
                          <strong>{KIND_LABELS[selectedGraphNode.kind] ?? selectedGraphNode.kind}: {selectedGraphNode.label}</strong>
                          <small>Ответ уточняется по этому элементу карты знаний.</small>
                        </div>
                        <button type="button" onClick={() => goToView("graph")}>Вернуться к графу</button>
                      </div>
                    )}

                    <div className="answer-block">
                      <span className="answer-block-label">Вывод</span>
                      <p className="answer-summary">{answer?.summary || "Выберите запрос или ячейку матрицы, чтобы собрать ответ."}</p>
                    </div>

                <div className="answer-tags">
                  <span>Фактов: {formatNumber(metrics?.facts)}</span>
                  <span>Документов: {formatNumber(metrics?.documents)}</span>
                  <span>Период: {metrics?.year_range || "не указан"}</span>
                  <span>Географий: {formatNumber(metrics?.geographies)}</span>
                  <span>Авторов/орг.: {formatNumber(metrics?.experts)}</span>
                </div>

                <div className="answer-sections">
                  <section className="answer-col consensus">
                    <header><CheckCircle2 size={15} />Наиболее подтверждено</header>
                    {(answer?.methods ?? []).length === 0 && <p className="answer-empty">Подтверждённых процессов пока нет.</p>}
                    {(answer?.methods ?? []).slice(0, 3).map((method, index) => (
                      <div className="answer-item" key={`${method.process}-${index}`}>
                        <div className="answer-item-top">
                          <strong>{method.process || "процесс не указан"}</strong>
                          <span>{formatNumber(method.facts)} фактов · {formatNumber(method.documents)} док.</span>
                        </div>
                        {method.top_results && <small>{method.top_results}</small>}
                      </div>
                    ))}
                  </section>

                  <section className="answer-col attention">
                    <header><AlertTriangle size={15} />Зоны разногласий и пробелов</header>
                    {(answer?.potential_conflicts ?? []).length === 0 && (answer?.gaps ?? []).length === 0 && (
                      <p className="answer-empty">Явных разногласий и критичных пробелов не выявлено.</p>
                    )}
                    {(answer?.potential_conflicts ?? []).slice(0, 2).map((conflict, index) => (
                      <div className="answer-item" key={`c-${index}`}>
                        <div className="answer-item-top">
                          <strong>{[conflict.material, conflict.process].filter(Boolean).join(" · ") || "связка"}</strong>
                        </div>
                        <small>{conflict.result_property}: расходятся значения {(conflict.values ?? []).slice(0, 4).join(" / ")}</small>
                      </div>
                    ))}
                    {(answer?.gaps ?? []).slice(0, 2).map((gap, index) => (
                      <div className="answer-item" key={`g-${index}`}>
                        <div className="answer-item-top">
                          <strong>{gap.gap}</strong>
                        </div>
                        {gap.detail && <small>{gap.detail}</small>}
                      </div>
                    ))}
                  </section>
                </div>

                <div className="answer-meta-grid">
                  <button className="answer-jump" onClick={() => goToView("graph")}>
                    <Network size={16} />
                    <div><strong>{formatNumber(flow.nodes.length)}</strong><span>узлов в графе ответа</span></div>
                  </button>
                  <button className="answer-jump" onClick={() => goToView("insights")}>
                    <AlertTriangle size={16} />
                    <div><strong>{formatNumber((answer?.potential_conflicts ?? []).length)}</strong><span>противоречий к проверке</span></div>
                  </button>
                  <button className="answer-jump" onClick={() => goToView("evidence")}>
                    <FileText size={16} />
                    <div><strong>{formatNumber((answer?.evidence_rows ?? []).length)}</strong><span>доказательных цитат</span></div>
                  </button>
                </div>

                {confidenceCounts.total > 0 && (
                  <div className="confidence-strip">
                    <div className="mini-chart-head">Индекс подтверждённости фактов</div>
                    <p className="confidence-help">{confidenceHelpText}</p>
                    <div className="cbar">
                      {confidenceCounts.high > 0 && <span className="cseg high" style={{ flexGrow: confidenceCounts.high }} title={`Высокая: ${confidenceCounts.high}`} />}
                      {confidenceCounts.medium > 0 && <span className="cseg medium" style={{ flexGrow: confidenceCounts.medium }} title={`Средняя: ${confidenceCounts.medium}`} />}
                      {confidenceCounts.low > 0 && <span className="cseg low" style={{ flexGrow: confidenceCounts.low }} title={`Низкая: ${confidenceCounts.low}`} />}
                      {confidenceCounts.unknown > 0 && <span className="cseg unknown" style={{ flexGrow: confidenceCounts.unknown }} title={`Не указана: ${confidenceCounts.unknown}`} />}
                    </div>
                    <div className="cbar-legend">
                      <span><i className="high" />Высокая {formatNumber(confidenceCounts.high)}</span>
                      <span><i className="medium" />Средняя {formatNumber(confidenceCounts.medium)}</span>
                      <span><i className="low" />Низкая {formatNumber(confidenceCounts.low)}</span>
                      {confidenceCounts.unknown > 0 && <span><i className="unknown" />Не указана {formatNumber(confidenceCounts.unknown)}</span>}
                    </div>
                  </div>
                )}
                  </>
                )}
              </article>

              <aside className="panel related-panel">
                <div className="panel-title">
                  <div>
                    <FlaskConical size={18} />
                    <h2>Факты-основания</h2>
                  </div>
                  <span className="panel-count">{(queryResult?.facts ?? []).length}</span>
                </div>
                <div className="fact-stack">
                  {isInitialQueryLoading && (
                    <div className="empty-state">
                      <Loader2 size={24} className="spin" />
                      <strong>Подбираем факты-основания</strong>
                      <span>После поиска здесь появятся факты, на которых строится аналитический ответ.</span>
                    </div>
                  )}
                  {!isInitialQueryLoading && (queryResult?.facts ?? []).length === 0 && (
                    <div className="empty-state">
                      <FlaskConical size={24} />
                      <strong>Факты пока не выбраны</strong>
                      <span>Запустите поиск, выберите сценарий или ячейку матрицы, чтобы увидеть факты-основания.</span>
                    </div>
                  )}
                  {(queryResult?.facts ?? []).slice(0, 6).map((fact, index) => {
                    const target = factQueryTarget(fact);
                    const meta = factMeta(fact);
                    return (
                      <button
                        className="fact-card"
                        key={`${fact.source_file}-${index}`}
                        onClick={() => target && runQuery(target)}
                      >
                        <div className="fact-card-head">
                          <strong>Факт {index + 1}</strong>
                          <span className={`confidence-pill ${fact.confidence || "unknown"}`}>{confidenceLabel(fact.confidence)}</span>
                        </div>

                        <div className="fact-path" aria-label="Цепочка эксперимента">
                          <span>{fact.material || "материал не указан"}</span>
                          <i />
                          <span>{fact.process || "процесс не указан"}</span>
                          <i />
                          <span>{fact.result_property || "показатель не указан"}</span>
                        </div>

                        <p className="fact-reason">{relatedReason(fact)}</p>

                        <div className="fact-result">
                          <span>Результат</span>
                          <strong>{factResult(fact)}</strong>
                        </div>

                        <dl className="fact-evidence">
                          <dt>Условия</dt>
                          <dd>{conditionsText(fact)}</dd>
                          {meta.length > 0 && (
                            <>
                              <dt>Контекст</dt>
                              <dd>{meta.join(" · ")}</dd>
                            </>
                          )}
                        </dl>

                        <div className="fact-source">
                          <span>{fact.source_file || "источник не указан"}</span>
                          <small>Собрать ответ по этому факту</small>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </aside>
            </section>

            <section className="overview-support" aria-label="Быстрые сценарии и состояние корпуса">
              <section className="support-section scenario-section">
                <div className="section-heading">
                  <span>Быстрый старт</span>
                  <strong>Готовые R&D-сценарии</strong>
                </div>
                <div className="preset-row preset-row-compact" aria-label="Сценарии из ТЗ">
                  {dashboard?.presets.map((preset) => (
                    <button
                      key={preset.label}
                      className={activePreset === preset.label ? "preset active" : "preset"}
                      onClick={() => runPreset(preset)}
                      title={preset.description}
                    >
                      <strong>{preset.label}</strong>
                      <span className={`preset-status ${preset.status === "пробел" ? "gap" : "partial"}`}>{preset.status}</span>
                    </button>
                  ))}
                </div>
              </section>

              <section className="support-section metrics-section">
                <div className="section-heading">
                  <span>Состояние корпуса</span>
                  <strong>Индекс графа</strong>
                </div>
                <div className="stat-bar stat-bar-compact">
                  {statItems.map((item) => {
                    const Icon = item.icon;
                    return (
                      <div className="stat-chip" key={item.label}>
                        <Icon size={17} />
                        <div>
                          <strong>{formatNumber(item.value)}</strong>
                          <span>{item.label}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            </section>
          </>
        )}

        {view === "graph" && (
          <section className="panel graph-view">
            <div className="panel-title">
              <div>
                <Network size={18} />
                <h2>Цепочки знаний</h2>
              </div>
              <div className="graph-legend">
                <span className="dot expert" /> эксперт
                <span className="dot material" /> материал
                <span className="dot process" /> процесс
                <span className="dot property" /> показатель
                <span className="dot document" /> источник
              </div>
            </div>
            <p className="panel-lede">
              {flow.nodes.length > 0
                ? `Связка «${answer?.title || searchValue}»: ${flow.nodes.length} узлов, ${flow.edges.length} связей. Тяните узлы, кликните — чтобы уточнить запрос.`
                : "Задайте запрос или выберите ячейку матрицы, чтобы построить граф."}
            </p>
            <div className="graph-details">
              <div>
                <span>{selectedGraphNode ? "Выбранный узел" : "Как читать граф"}</span>
                <strong>
                  {selectedGraphNode
                    ? `${KIND_LABELS[selectedGraphNode.kind] ?? selectedGraphNode.kind}: ${selectedGraphNode.label}`
                    : "Эксперт → материал → процесс → показатель → источник"}
                </strong>
              </div>
              <small>
                {selectedGraphNode
                  ? "Клик по узлу запускает уточняющий запрос по этому элементу карты знаний."
                  : "Узлы показывают сущности из ответа, а стрелки — извлечённые связи между ними."}
              </small>
            </div>
            <div className="flow-wrap tall">
              {flow.nodes.length === 0 ? (
                <div className="flow-empty">
                  <Network size={34} />
                  <span>Построим цепочку «эксперт → материал → процесс → показатель → источник» после запроса</span>
                </div>
              ) : (
                <ReactFlow
                  nodes={flow.nodes}
                  edges={flow.edges}
                  nodeTypes={nodeTypes}
                  fitView
                  fitViewOptions={{ padding: 0.2, maxZoom: 1.1 }}
                  minZoom={0.25}
                  maxZoom={1.75}
                  nodesDraggable
                  proOptions={{ hideAttribution: true }}
                  onNodeClick={(_, node) => {
                    const nodeData = node.data as EntityNodeData;
                    const label = String(nodeData?.label ?? "");
                    if (label) {
                      setSelectedGraphNode(nodeData);
                      setSelectedCell(null);
                      setSearchValue(label);
                      runQuery(label);
                    }
                  }}
                >
                  <Background color="#dce5f2" gap={20} />
                  <Controls showInteractive={false} />
                </ReactFlow>
              )}
            </div>
          </section>
        )}

        {view === "matrix" && (
          <>
            <section className="panel matrix-panel matrix-view">
              <div className="matrix-header">
                <div>
                  <h2>Покрытие R&amp;D-связок</h2>
                  <p>Каждая ячейка — сколько подтверждённых фактов связывает строку и столбец. Кликните ячейку, чтобы собрать ответ и граф по связке.</p>
                </div>
                <div className="matrix-controls">
                  <label>
                    Строки
                    <select value={axis1} onChange={(event) => setAxis1(event.target.value)}>
                      <option value="material">Материалы</option>
                      <option value="process">Процессы</option>
                      <option value="property">Показатели</option>
                    </select>
                  </label>
                  <label>
                    Столбцы
                    <select value={axis2} onChange={(event) => setAxis2(event.target.value)}>
                      <option value="process">Процессы</option>
                      <option value="material">Материалы</option>
                      <option value="property">Показатели</option>
                    </select>
                  </label>
                  <label>
                    Числовое условие
                    <select value={condition} onChange={(event) => setCondition(event.target.value)}>
                      <option value="">нет</option>
                      <option value="температура">температура</option>
                      <option value="давление">давление</option>
                      <option value="концентрация">концентрация</option>
                      <option value="скорость">скорость</option>
                    </select>
                  </label>
                </div>
              </div>

              <div className="matrix-legend">
                {MATRIX_LEGEND.map((item) => (
                  <span className={`legend ${item.className}`} key={item.className}>
                    <strong>{item.range}</strong>
                    {item.label}
                  </span>
                ))}
              </div>

              <div className="matrix-scroll tall">
                <table className="gap-matrix">
                  <thead>
                    <tr>
                      <th>{matrix?.axisLabels.axis1 ?? "Материал"}</th>
                      {matrix?.columns.map((column) => <th key={column}>{column}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix?.rows.map((row) => (
                      <tr key={row}>
                        <th>{row}</th>
                        {matrix.columns.map((column) => {
                          const cell = matrixLookup.get(`${row}///${column}`);
                          const isSelected = selectedCell?.row === row && selectedCell?.column === column;
                          return (
                            <td key={column}>
                              <button
                                className={`matrix-cell ${cell?.state ?? "empty"} ${isSelected ? "selected" : ""}`}
                                onClick={() => cell && selectMatrixCell(cell)}
                                title={`${row} × ${column}: ${cell?.stateLabel ?? "нет данных"}`}
                              >
                                {cell?.count ?? 0}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="matrix-footer">
                <label>Строк: <input type="range" min={8} max={24} value={top1} onChange={(event) => setTop1(Number(event.target.value))} /> {top1}</label>
                <label>Столбцов: <input type="range" min={6} max={18} value={top2} onChange={(event) => setTop2(Number(event.target.value))} /> {top2}</label>
                <button className="soft-button" onClick={downloadMarkdown} disabled={!answer?.markdown}><Download size={16} />Экспорт ответа</button>
              </div>
            </section>

            <section className="panel gap-panel">
              <div className="panel-title">
                <div>
                  <ScanSearch size={18} />
                  <h2>Кандидаты на исследование</h2>
                </div>
                <span className="panel-count warn">{(matrix?.gaps ?? []).length}</span>
              </div>
              <p className="panel-lede">Связки с высоким интересом, но без подтверждённых совместных фактов — приоритеты для новых экспериментов.</p>
              <div className="gap-grid">
                {(matrix?.gaps ?? []).slice(0, 8).map((gap) => (
                  <button className="gap-card" key={`${gap.row}-${gap.column}`} onClick={() => selectMatrixCell(gap)}>
                    <strong>{gap.row} × {gap.column}</strong>
                    <span>приоритет {gap.interest}</span>
                    <small>темы по отдельности: {gap.rowTotal} и {gap.columnTotal}</small>
                  </button>
                ))}
              </div>
            </section>
          </>
        )}

        {view === "insights" && (
          <>
            <div className="insights-2col">
              <article className="panel geo-panel">
                <div className="panel-title">
                  <div>
                    <Globe2 size={18} />
                    <h2>География практики</h2>
                  </div>
                  <span className="panel-count">{(answer?.geo_breakdown ?? []).length}</span>
                </div>
                <p className="panel-lede">Отечественная и зарубежная практика по выбранному запросу.</p>
                <div className="geo-list">
                  {(answer?.geo_breakdown ?? []).length === 0 && (
                    <p className="empty-hint">У найденных фактов нет географической привязки — это пробел корпуса.</p>
                  )}
                  {(answer?.geo_breakdown ?? []).slice(0, 12).map((row, index) => (
                    <button
                      className="geo-row"
                      key={`${row.location_geo}-${index}`}
                      onClick={() => row.location_geo && runQuery(row.location_geo)}
                    >
                      <div className="geo-name">
                        <Globe2 size={15} />
                        <strong>{row.location_geo || "—"}</strong>
                      </div>
                      <div className="geo-meta">
                        <span>{formatNumber(row.facts)} фактов</span>
                        <span>{formatNumber(row.documents)} док.</span>
                        {row.year_range && <span>{row.year_range}</span>}
                      </div>
                    </button>
                  ))}
                </div>
              </article>

              <article className="panel conflict-panel">
                <div className="panel-title">
                  <div>
                    <AlertTriangle size={18} />
                    <h2>Потенциальные противоречия</h2>
                  </div>
                  <span className="panel-count warn">{(answer?.potential_conflicts ?? []).length}</span>
                </div>
                <p className="panel-lede">Это не ошибка системы: здесь собраны расхождения значений, контекстов или направлений эффекта, которые стоит передать эксперту на проверку.</p>
                <div className="conflict-list">
                  {(answer?.potential_conflicts ?? []).length === 0 && (
                    <p className="empty-hint">Явных противоречий по выбранному набору фактов не найдено.</p>
                  )}
                  {(answer?.potential_conflicts ?? []).slice(0, 6).map((conflict, index) => (
                    <article className="conflict-card" key={index}>
                      <header>
                        <strong>{[conflict.material, conflict.process].filter(Boolean).join(" · ") || "связка"}</strong>
                        <span className="conflict-status">{conflict.status || "проверить"}</span>
                      </header>
                      <p className="conflict-prop">{conflict.result_property}</p>
                      <div className="conflict-values">
                        {(conflict.values ?? []).slice(0, 6).map((value, i) => (
                          <span key={i}>{value}</span>
                        ))}
                      </div>
                      {conflict.example_quote && <p className="conflict-quote">«{conflict.example_quote}»</p>}
                      <footer>
                        <span>{formatNumber(conflict.facts)} фактов</span>
                        <span>{(conflict.sources ?? []).length} источник(ов)</span>
                      </footer>
                    </article>
                  ))}
                </div>
              </article>
            </div>

            <article className="panel methods-panel">
              <div className="panel-title">
                <div>
                  <Route size={18} />
                  <h2>Методы и процессы</h2>
                </div>
                <span className="panel-count">{(answer?.methods ?? []).length}</span>
              </div>
              <p className="panel-lede">Автогруппировка литобзора по процессам с трассировкой к источникам.</p>
              <div className="methods-grid">
                {(answer?.methods ?? []).length === 0 && <p className="empty-hint">Процессы не выделены.</p>}
                {(answer?.methods ?? []).slice(0, 9).map((method, index) => (
                  <button
                    className="method-row"
                    key={`${method.process}-${index}`}
                    onClick={() => method.process && runQuery(method.process)}
                  >
                    <div className="method-top">
                      <strong>{method.process || "процесс не указан"}</strong>
                      <span>{formatNumber(method.facts)} фактов · {formatNumber(method.documents)} док.</span>
                    </div>
                    {method.top_materials && <small>Материалы: {method.top_materials}</small>}
                    {method.top_results && <small className="muted">Результаты: {method.top_results}</small>}
                  </button>
                ))}
              </div>
            </article>
          </>
        )}

        {view === "evidence" && (
          <div className="evidence-view">
            <article className="panel evidence-panel">
              <div className="panel-title">
                <div>
                  <FileText size={18} />
                  <h2>Доказательства</h2>
                </div>
                <span className="panel-count">{(answer?.evidence_rows ?? []).length}</span>
              </div>
              <p className="panel-lede">Каждый вывод трассируется к источнику с прямой цитатой и уровнем достоверности.</p>
              <div className="evidence-grid">
                {(answer?.evidence_rows ?? []).length === 0 && <p className="empty-hint">Нет доказательной базы для запроса.</p>}
                {(answer?.evidence_rows ?? []).slice(0, 12).map((row, index) => (
                  <article className="evidence-card" key={`${row.source_file}-${index}`}>
                    <div className="evidence-top">
                      <strong>{row.source_file || "Источник не указан"}</strong>
                      <span className={`confidence-pill ${row.confidence || "unknown"}`}>{confidenceLabel(row.confidence)}</span>
                    </div>
                    <p>{row.source_quote || factResult(row)}</p>
                    <footer>
                      <span>{conditionsText(row)}</span>
                      <span>{row.year || "год не указан"}</span>
                    </footer>
                  </article>
                ))}
              </div>
            </article>

            <aside className="panel gap-panel">
              <div className="panel-title">
                <div>
                  <ScanSearch size={18} />
                  <h2>Кандидаты на исследование</h2>
                </div>
              </div>
              <p className="panel-lede">Приоритетные пробелы из матрицы.</p>
              <div className="gap-list">
                {(matrix?.gaps ?? []).slice(0, 6).map((gap) => (
                  <button className="gap-card" key={`${gap.row}-${gap.column}`} onClick={() => selectMatrixCell(gap)}>
                    <strong>{gap.row} × {gap.column}</strong>
                    <span>приоритет {gap.interest}</span>
                    <small>темы по отдельности: {gap.rowTotal} и {gap.columnTotal}</small>
                  </button>
                ))}
              </div>
            </aside>
          </div>
        )}

        {view === "entities" && (
          <section className="entity-strip">
            {["materials", "processes", "properties", "experts"].map((key) => {
              const meta = ENTITY_META[key];
              const Icon = meta.icon;
              return (
                <article className="panel entity-panel" key={key}>
                  <h3><Icon size={16} />{meta.label}</h3>
                  {(dashboard?.topEntities[key] ?? []).slice(0, 10).map((entity) => (
                    <button key={entity.id} onClick={() => {
                      setSearchValue(entity.name);
                      runQuery(entity.name);
                    }}>
                      <span>{entity.name}</span>
                      <strong>{formatNumber(entity.mentions)}</strong>
                    </button>
                  ))}
                </article>
              );
            })}
          </section>
        )}

        <footer className="app-footer">
          <span>Научный клубок — карта знаний R&amp;D для горно-металлургической отрасли</span>
          <span>Граф: {formatNumber(dashboard?.counts.nodes)} узлов · {formatNumber(dashboard?.counts.links)} связей · детерминированный синтез с трассировкой к источникам</span>
        </footer>
      </main>
    </div>
  );
}
