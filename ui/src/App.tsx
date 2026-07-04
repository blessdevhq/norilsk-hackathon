import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node
} from "@xyflow/react";
import {
  AlertTriangle,
  Boxes,
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
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

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
  if (!Array.isArray(fact.conditions) || fact.conditions.length === 0) return "Условия не выделены";
  return fact.conditions
    .slice(0, 3)
    .map((condition) => [condition.parameter, condition.value, condition.unit].filter(Boolean).join(" "))
    .join("; ");
}

function cellContext(cell: MatrixCell, matrix: MatrixResponse): MatrixCell {
  return {
    ...cell,
    axis1: matrix.axis1,
    axis2: matrix.axis2,
    condition_parameter: matrix.condition_parameter ?? null
  };
}

function nodeStyle(kind: string) {
  const styles: Record<string, React.CSSProperties> = {
    material: { borderColor: "#55b883", background: "#e9f8ef", color: "#124633" },
    process: { borderColor: "#6f94e8", background: "#edf3ff", color: "#1b3f8d" },
    property: { borderColor: "#9d78e8", background: "#f4efff", color: "#4c238d" },
    document: { borderColor: "#9aa8bf", background: "#f4f6fb", color: "#334155" },
    expert: { borderColor: "#4bb8be", background: "#e9fbfb", color: "#0f5157" },
    gap: { borderColor: "#f0ae2c", background: "#fff7df", color: "#7b4b00" }
  };
  return {
    border: "1px solid #d8e0ee",
    borderRadius: 14,
    padding: "10px 13px",
    fontSize: 12,
    fontWeight: 700,
    width: 148,
    textAlign: "center" as const,
    boxShadow: "0 10px 24px rgba(30, 41, 59, 0.08)",
    ...(styles[kind] ?? {})
  };
}

function flowLayout(payload?: GraphPayload) {
  if (!payload) return { nodes: [], edges: [] };
  const centerX = 280;
  const centerY = 190;
  const radiusX = 250;
  const radiusY = 145;
  const nodes: Node[] = payload.nodes.map((node, index) => {
    const angle = (index / Math.max(1, payload.nodes.length)) * Math.PI * 2;
    const isFirst = index === 0;
    return {
      id: node.id,
      data: { label: node.label },
      position: isFirst
        ? { x: centerX, y: centerY }
        : { x: centerX + Math.cos(angle) * radiusX, y: centerY + Math.sin(angle) * radiusY },
      style: nodeStyle(node.kind)
    };
  });

  const edges: Edge[] = payload.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, color: "#6b7a90" },
    style: { stroke: "#8a9bb5", strokeWidth: 1.4 },
    labelStyle: { fill: "#536176", fontSize: 10, fontWeight: 600 },
    labelBgStyle: { fill: "#ffffff", fillOpacity: 0.85 }
  }));
  return { nodes, edges };
}

const NAV_SECTIONS = [
  { id: "answer", label: "Поиск и ответ", icon: Search },
  { id: "graph", label: "Граф знаний", icon: Network },
  { id: "insights", label: "Гео и противоречия", icon: ScanSearch },
  { id: "matrix", label: "Матрица пробелов", icon: LayoutGrid },
  { id: "evidence", label: "Источники", icon: FileText },
  { id: "entities", label: "Сущности", icon: Boxes }
] as const;

const ENTITY_META: Record<string, { label: string; icon: typeof Boxes }> = {
  materials: { label: "Материалы", icon: Boxes },
  processes: { label: "Процессы", icon: Route },
  properties: { label: "Показатели", icon: LayoutGrid },
  experts: { label: "Эксперты", icon: Users }
};

export default function App() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [graph, setGraph] = useState<GraphPayload | undefined>();
  const [searchValue, setSearchValue] = useState("");
  const [activePreset, setActivePreset] = useState("");
  const [selectedCell, setSelectedCell] = useState<MatrixCell | null>(null);
  const [axis1, setAxis1] = useState("material");
  const [axis2, setAxis2] = useState("process");
  const [condition, setCondition] = useState("");
  const [top1, setTop1] = useState(15);
  const [top2, setTop2] = useState(10);
  const [loading, setLoading] = useState(true);
  const [queryLoading, setQueryLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState<string>("answer");
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

  useEffect(() => {
    if (loading) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible?.target.id) setActiveSection(visible.target.id);
      },
      { rootMargin: "-45% 0px -45% 0px", threshold: [0, 0.25, 0.5, 1] }
    );
    NAV_SECTIONS.forEach((section) => {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [loading]);

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

  const statItems = useMemo(() => {
    const counts = dashboard?.counts;
    return [
      { icon: Network, label: "Узлов графа", value: counts?.nodes },
      { icon: Route, label: "Связей", value: counts?.links },
      { icon: Sparkles, label: "Фактов", value: counts?.facts },
      { icon: FileText, label: "Документов", value: counts?.documents },
      { icon: Boxes, label: "Материалов", value: counts?.materials },
      { icon: FlaskConical, label: "Процессов", value: counts?.processes },
      { icon: Users, label: "Экспертов", value: counts?.experts },
      { icon: Database, label: "Оборудование", value: counts?.equipment }
    ];
  }, [dashboard]);

  function scrollToSection(id: string) {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setSelectedCell(null);
    setActivePreset("");
    void refreshQuery(searchValue);
    scrollToSection("answer");
  }

  function runPreset(preset: Preset) {
    setActivePreset(preset.label);
    setSelectedCell(null);
    setSearchValue(preset.query);
    void refreshQuery(preset.query, preset.filters);
  }

  function selectMatrixCell(cell: MatrixCell) {
    if (!matrix) return;
    const context = cellContext(cell, matrix);
    setSelectedCell(context);
    setSearchValue(`${context.row} × ${context.column}`);
    void refreshQuery(`${context.row} × ${context.column}`, {}, context);
    scrollToSection("answer");
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
          {NAV_SECTIONS.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                className={activeSection === section.id ? "active" : ""}
                onClick={() => scrollToSection(section.id)}
              >
                <Icon size={19} />
                {section.label}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-verify">
          <div className="verify-head">
            <ShieldCheck size={16} />
            Верификация
          </div>
          <strong>{dashboard?.graph.verificationStatus === "auto_extracted" ? "Авто-извлечение" : dashboard?.graph.verificationStatus || "—"}</strong>
          <small>Актуализировано {formatDate(dashboard?.graph.updatedAt)}</small>
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
              placeholder="Введите R&D вопрос: материал, процесс, условие, география, период"
            />
            <button type="submit" disabled={queryLoading}>
              {queryLoading ? "Ищу…" : "Найти"}
            </button>
          </form>
          <div className="verify-badge">
            <ShieldCheck size={16} />
            <div>
              <strong>Проверяемо</strong>
              <span>обновлено {formatDate(dashboard?.graph.updatedAt)}</span>
            </div>
          </div>
          <button className="export-button" onClick={downloadMarkdown} disabled={!answer?.markdown}>
            <Download size={18} />
            Экспорт .md
          </button>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section className="stat-bar">
          {statItems.map((item) => {
            const Icon = item.icon;
            return (
              <div className="stat-chip" key={item.label}>
                <Icon size={18} />
                <div>
                  <strong>{formatNumber(item.value)}</strong>
                  <span>{item.label}</span>
                </div>
              </div>
            );
          })}
        </section>

        <section className="preset-row" aria-label="Сценарии из ТЗ">
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
        </section>

        <section className="hero-grid" id="answer">
          <article className={`panel answer-panel ${queryLoading ? "is-loading" : ""}`}>
            <div className="panel-title">
              <div>
                <Sparkles size={18} />
                <h2>Краткий ответ</h2>
              </div>
              <div className="confidence-ring" style={{ ["--confidence" as string]: `${confidencePercent}%` }}>
                <span>{confidencePercent}%</span>
              </div>
            </div>
            <p>{answer?.summary || "Выберите запрос или ячейку матрицы, чтобы собрать ответ."}</p>
            <div className="answer-tags">
              <span>Фактов: {formatNumber(metrics?.facts)}</span>
              <span>Документов: {formatNumber(metrics?.documents)}</span>
              <span>Период: {metrics?.year_range || "не указан"}</span>
              <span>Географий: {formatNumber(metrics?.geographies)}</span>
              <span>Экспертов: {formatNumber(metrics?.experts)}</span>
            </div>
            <div className="mini-chart">
              <div className="mini-chart-head">Достоверность фактов в графе</div>
              <ResponsiveContainer width="100%" height={92}>
                <BarChart data={dashboard?.confidence ?? []}>
                  <CartesianGrid vertical={false} stroke="#eef2f7" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                  <YAxis hide />
                  <Tooltip formatter={(value: number) => [formatNumber(value), "фактов"]} />
                  <Bar dataKey="value" radius={[7, 7, 0, 0]} fill="#1da690" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="panel graph-panel" id="graph">
            <div className="panel-title">
              <div>
                <Network size={18} />
                <h2>Граф знаний</h2>
              </div>
              <div className="graph-legend">
                <span className="dot material" /> материал
                <span className="dot process" /> процесс
                <span className="dot property" /> показатель
                <span className="dot document" /> источник
              </div>
            </div>
            <div className="flow-wrap">
              {flow.nodes.length === 0 ? (
                <div className="flow-empty">
                  <Network size={30} />
                  <span>Задайте запрос — построим цепочку «материал → процесс → показатель → источник»</span>
                </div>
              ) : (
                <ReactFlow
                  nodes={flow.nodes}
                  edges={flow.edges}
                  fitView
                  minZoom={0.35}
                  maxZoom={1.4}
                  onNodeClick={(_, node) => {
                    const label = String(node.data?.label ?? "");
                    if (label) {
                      setSearchValue(label);
                      void refreshQuery(label);
                    }
                  }}
                >
                  <Background color="#dce5f2" gap={18} />
                  <Controls showInteractive={false} />
                </ReactFlow>
              )}
            </div>
          </article>

          <aside className="panel related-panel">
            <div className="panel-title">
              <div>
                <FlaskConical size={18} />
                <h2>Связанные эксперименты</h2>
              </div>
            </div>
            <div className="fact-stack">
              {(queryResult?.facts ?? []).length === 0 && <p className="empty-hint">Нет связанных экспериментов.</p>}
              {(queryResult?.facts ?? []).slice(0, 5).map((fact, index) => (
                <button className="fact-card" key={`${fact.source_file}-${index}`} onClick={() => void refreshQuery(fact.material || fact.process || "")}>
                  <div className="fact-card-head">
                    <strong>E-{String(index + 1).padStart(4, "0")}</strong>
                    <span className={`confidence-pill ${fact.confidence || "unknown"}`}>{confidenceLabel(fact.confidence)}</span>
                  </div>
                  <dl>
                    <dt>Материал</dt><dd>{fact.material || "не указан"}</dd>
                    <dt>Процесс</dt><dd>{fact.process || "не указан"}</dd>
                    <dt>Результат</dt><dd>{factResult(fact)}</dd>
                  </dl>
                  <small>{fact.source_file || "источник не указан"}</small>
                </button>
              ))}
            </div>
          </aside>
        </section>

        <section className="insight-grid" id="insights">
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
              {(answer?.geo_breakdown ?? []).slice(0, 6).map((row, index) => (
                <button
                  className="geo-row"
                  key={`${row.location_geo}-${index}`}
                  onClick={() => row.location_geo && void refreshQuery(row.location_geo)}
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
            <p className="panel-lede">Расхождения значений и направлений эффекта — сигнал для экспертной проверки.</p>
            <div className="conflict-list">
              {(answer?.potential_conflicts ?? []).length === 0 && (
                <p className="empty-hint">Явных противоречий по выбранному набору фактов не найдено.</p>
              )}
              {(answer?.potential_conflicts ?? []).slice(0, 4).map((conflict, index) => (
                <article className="conflict-card" key={index}>
                  <header>
                    <strong>{[conflict.material, conflict.process].filter(Boolean).join(" · ") || "связка"}</strong>
                    <span className="conflict-status">{conflict.status || "проверить"}</span>
                  </header>
                  <p className="conflict-prop">{conflict.result_property}</p>
                  <div className="conflict-values">
                    {(conflict.values ?? []).slice(0, 5).map((value, i) => (
                      <span key={i}>{value}</span>
                    ))}
                  </div>
                  <footer>
                    <span>{formatNumber(conflict.facts)} фактов</span>
                    <span>{(conflict.sources ?? []).length} источник(ов)</span>
                  </footer>
                </article>
              ))}
            </div>
          </article>

          <article className="panel methods-panel">
            <div className="panel-title">
              <div>
                <Route size={18} />
                <h2>Методы и процессы</h2>
              </div>
              <span className="panel-count">{(answer?.methods ?? []).length}</span>
            </div>
            <p className="panel-lede">Автогруппировка литобзора по процессам с трассировкой к источникам.</p>
            <div className="methods-list">
              {(answer?.methods ?? []).length === 0 && <p className="empty-hint">Процессы не выделены.</p>}
              {(answer?.methods ?? []).slice(0, 5).map((method, index) => (
                <button
                  className="method-row"
                  key={`${method.process}-${index}`}
                  onClick={() => method.process && void refreshQuery(method.process)}
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
        </section>

        <section className="lower-grid" id="matrix">
          <article className="panel matrix-panel">
            <div className="matrix-header">
              <div>
                <h2>Матрица пробелов</h2>
                <p>Главный рабочий вид: показывает, какие R&amp;D-связки покрыты источниками, а где нужно планировать исследование.</p>
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
              <span className="legend empty">не исследовано</span>
              <span className="legend single">единичные данные</span>
              <span className="legend partial">частично изучено</span>
              <span className="legend covered">изучено много</span>
            </div>

            <div className="matrix-scroll">
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
          </article>

          <aside className="panel evidence-panel" id="evidence">
            <div className="panel-title">
              <div>
                <FileText size={18} />
                <h2>Доказательства</h2>
              </div>
              <span className="panel-count">{(answer?.evidence_rows ?? []).length}</span>
            </div>
            <div className="evidence-list">
              {(answer?.evidence_rows ?? []).length === 0 && <p className="empty-hint">Нет доказательной базы для запроса.</p>}
              {(answer?.evidence_rows ?? []).slice(0, 5).map((row, index) => (
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

            <div className="gap-candidates">
              <h3>Кандидаты на исследование</h3>
              {(matrix?.gaps ?? []).slice(0, 4).map((gap) => (
                <button key={`${gap.row}-${gap.column}`} onClick={() => selectMatrixCell(gap)}>
                  <strong>{gap.row} × {gap.column}</strong>
                  <span>приоритет {gap.interest}; темы отдельно: {gap.rowTotal} и {gap.columnTotal}</span>
                </button>
              ))}
            </div>
          </aside>
        </section>

        <section className="entity-strip" id="entities">
          {["materials", "processes", "properties", "experts"].map((key) => {
            const meta = ENTITY_META[key];
            const Icon = meta.icon;
            return (
              <article className="panel entity-panel" key={key}>
                <h3><Icon size={16} />{meta.label}</h3>
                {(dashboard?.topEntities[key] ?? []).slice(0, 5).map((entity) => (
                  <button key={entity.id} onClick={() => {
                    setSearchValue(entity.name);
                    void refreshQuery(entity.name);
                    scrollToSection("answer");
                  }}>
                    <span>{entity.name}</span>
                    <strong>{formatNumber(entity.mentions)}</strong>
                  </button>
                ))}
              </article>
            );
          })}
        </section>

        <footer className="app-footer">
          <span>Научный клубок — карта знаний R&amp;D для горно-металлургической отрасли</span>
          <span>Граф: {formatNumber(dashboard?.counts.nodes)} узлов · {formatNumber(dashboard?.counts.links)} связей · детерминированный синтез ответа с трассировкой к источникам</span>
        </footer>
      </main>
    </div>
  );
}
