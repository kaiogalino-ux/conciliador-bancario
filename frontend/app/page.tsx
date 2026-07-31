"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type ReactNode,
} from "react";

import {
  baixarResultado,
  enviarConciliacao,
  type PendingItem,
  type ReconciliationResult,
} from "../lib/api";

type UploadKind = "erp" | "bank";

const PAGE_SIZE = 8;

/**
 * Onde esta versão publicada processa os arquivos, derivado da URL da API.
 *
 * O default repete o de lib/api.ts de propósito: sem NEXT_PUBLIC_API_URL
 * configurada, o destino é o uvicorn da própria máquina. A variável é inlinada
 * no build (a página é estática), então o modo é fixo por publicação — que é
 * exatamente o necessário aqui: o aviso precisa descrever o backend para onde
 * ESTA versão envia os arquivos, não um estado de runtime.
 */
const API_URL_CONFIGURADA =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Só considera local o que realmente é a própria máquina.
 *
 * A checagem é pelo hostname, não por substring: "https://localhost.exemplo.com"
 * contém "localhost" e é um host remoto. Qualquer URL que não dê para
 * interpretar cai em hospedado — na dúvida, a página nunca afirma que os
 * arquivos ficam no computador.
 */
function ehEnderecoLocal(url: string): boolean {
  let hostname: string;
  try {
    hostname = new URL(url).hostname;
  } catch {
    return false;
  }
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]" ||
    hostname.endsWith(".localhost")
  );
}

const MODO_LOCAL = ehEnderecoLocal(API_URL_CONFIGURADA);

const processingMessages = [
  "Lendo a estrutura dos arquivos",
  "Aplicando a regra de data exata",
  "Comparando valores e descrições",
  "Fechando lotes e duplicidades",
  "Preparando a planilha final",
];

function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M5 8.5A3.5 3.5 0 0 1 8.5 5h15A3.5 3.5 0 0 1 27 8.5v15a3.5 3.5 0 0 1-3.5 3.5h-15A3.5 3.5 0 0 1 5 23.5v-15Z" />
      <path d="M10 11h12M10 16h7M10 21h12" />
      <path d="m20 14 2.5 2.5L20 19" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" />
      <path d="M5 14v4.5A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5V14" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 3.5h6.8L19 8.7v11.8H7V3.5Z" />
      <path d="M13.5 3.8V9H19M10 13h6M10 16.5h6" />
    </svg>
  );
}

function BuildingIcon() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <path d="M6 24V7l8-4 8 4v17M3.5 24.5h21" />
      <path d="M10 9h2v2h-2zM16 9h2v2h-2zM10 14h2v2h-2zM16 14h2v2h-2zM10 19h2v2h-2zM16 19h2v2h-2z" />
    </svg>
  );
}

function BankIcon() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <path d="m3 10 11-7 11 7H3Z" />
      <path d="M6 12v9M11.3 12v9M16.7 12v9M22 12v9M3 24h22M5 21h18" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <circle cx="14" cy="14" r="11" />
      <path d="m8.5 14 3.5 3.5 7.5-8" />
    </svg>
  );
}

function ReviewIcon() {
  return (
    <svg viewBox="0 0 28 28" aria-hidden="true">
      <path d="M14 3.5 25 23H3L14 3.5Z" />
      <path d="M14 10v6M14 20h.01" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v12m0 0 4-4m-4 4-4-4" />
      <path d="M5 18v2h14v-2" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 5 5" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h13M13 6l6 6-6 6" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m7 7 10 10M17 7 7 17" />
    </svg>
  );
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatCurrency(value: number | null) {
  if (value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-");
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function formatPercent(value: number) {
  return `${value.toFixed(1).replace(".", ",")}%`;
}

function UploadZone({
  kind,
  title,
  description,
  accept,
  file,
  onSelect,
  onRemove,
}: {
  kind: UploadKind;
  title: string;
  description: string;
  accept: string;
  file: File | null;
  onSelect: (kind: UploadKind, file: File) => void;
  onRemove: (kind: UploadKind) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    const droppedFile = event.dataTransfer.files[0];
    if (droppedFile) onSelect(kind, droppedFile);
  };

  return (
    <div className={`upload-card ${file ? "has-file" : ""}`}>
      <div className="upload-card__heading">
        <span className="source-icon">
          {kind === "erp" ? <BuildingIcon /> : <BankIcon />}
        </span>
        <span>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
      </div>

      <div
        className={`drop-zone ${dragActive ? "is-dragging" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) {
            setDragActive(false);
          }
        }}
        onDrop={handleDrop}
      >
        {file ? (
          <div className="file-ready">
            <span className="file-ready__icon">
              <FileIcon />
            </span>
            <span className="file-ready__copy">
              <strong title={file.name}>{file.name}</strong>
              <small>{formatFileSize(file.size)} · pronto para processar</small>
            </span>
            <button
              type="button"
              className="icon-button"
              onClick={() => onRemove(kind)}
              aria-label={`Remover ${file.name}`}
            >
              <CloseIcon />
            </button>
          </div>
        ) : (
          <>
            <span className="drop-zone__icon">
              <UploadIcon />
            </span>
            <strong>Arraste o arquivo aqui</strong>
            <span>ou selecione no computador</span>
            <button
              type="button"
              className="select-file-button"
              onClick={() => inputRef.current?.click()}
            >
              Selecionar arquivo
            </button>
          </>
        )}
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept={accept}
          onChange={(event) => {
            const selectedFile = event.target.files?.[0];
            if (selectedFile) onSelect(kind, selectedFile);
            event.currentTarget.value = "";
          }}
        />
      </div>
    </div>
  );
}

function MetricCard({
  tone,
  icon,
  label,
  value,
  detail,
}: {
  tone: "gestao" | "banco" | "success" | "review" | "danger";
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <span className="metric-card__icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

export default function Home() {
  const [erpFile, setErpFile] = useState<File | null>(null);
  const [bankFile, setBankFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [processingStep, setProcessingStep] = useState(0);
  const [formError, setFormError] = useState("");
  const [result, setResult] = useState<ReconciliationResult | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("Todos");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (!isProcessing) return;
    setProcessingStep(0);
    const timer = window.setInterval(() => {
      setProcessingStep((current) =>
        Math.min(current + 1, processingMessages.length - 1)
      );
    }, 1500);
    return () => window.clearInterval(timer);
  }, [isProcessing]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, result?.runId]);

  const selectFile = (kind: UploadKind, file: File) => {
    const extension = `.${file.name.split(".").pop()?.toLowerCase() || ""}`;
    const allowed =
      kind === "erp"
        ? [".xlsx", ".xls"]
        : [".ofx", ".xlsx", ".xls"];

    if (!allowed.includes(extension)) {
      setFormError(
        kind === "erp"
          ? "O arquivo da Gestão deve estar em formato XLSX ou XLS."
          : "O arquivo do banco deve estar em formato OFX, XLSX ou XLS."
      );
      return;
    }
    if (file.size > 30 * 1024 * 1024) {
      setFormError("Cada arquivo deve ter no máximo 30 MB.");
      return;
    }
    setFormError("");
    if (kind === "erp") setErpFile(file);
    else setBankFile(file);
  };

  const removeFile = (kind: UploadKind) => {
    if (kind === "erp") setErpFile(null);
    else setBankFile(null);
    setResult(null);
    setFormError("");
  };

  const executeReconciliation = async () => {
    if (!erpFile || !bankFile) {
      setFormError(
        "Adicione o relatório da Gestão e o extrato do banco antes de conciliar."
      );
      return;
    }

    setFormError("");
    setIsProcessing(true);
    setResult(null);

    try {
      const payload = await enviarConciliacao(erpFile, bankFile);
      setResult(payload);
      window.setTimeout(() => {
        document
          .getElementById("resultado")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "Não foi possível executar a conciliação."
      );
    } finally {
      setIsProcessing(false);
    }
  };

  const downloadResult = async () => {
    if (!result) return;

    setFormError("");
    setIsDownloading(true);
    try {
      await baixarResultado(result.downloadUrl);
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "Não foi possível baixar a planilha."
      );
    } finally {
      setIsDownloading(false);
    }
  };

  const filteredPending = useMemo(() => {
    if (!result) return [];
    const normalizedSearch = search.trim().toLocaleLowerCase("pt-BR");
    return result.pendentes.filter((item) => {
      const matchesStatus =
        statusFilter === "Todos" || item.status === statusFilter;
      const searchable = [
        item.data,
        item.origem,
        item.favorecido,
        item.status,
        item.motivo,
      ]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("pt-BR");
      return (
        matchesStatus &&
        (!normalizedSearch || searchable.includes(normalizedSearch))
      );
    });
  }, [result, search, statusFilter]);

  const totalPages = Math.max(
    1,
    Math.ceil(filteredPending.length / PAGE_SIZE)
  );
  const visiblePending = filteredPending.slice(
    (page - 1) * PAGE_SIZE,
    page * PAGE_SIZE
  );

  const periodLabel = result
    ? result.periodo.inicio && result.periodo.fim
      ? `${formatDate(result.periodo.inicio)} a ${formatDate(
          result.periodo.fim
        )}`
      : "Período identificado nos arquivos"
    : "Aguardando uma execução";

  return (
    <>
      <a className="skip-link" href="#conteudo">
        Ir para o conteúdo
      </a>

      <header className="app-header">
        <a className="brand" href="#inicio" aria-label="Conciliador Bancário — início">
          <span className="brand__mark">
            <BrandMark />
          </span>
          <span className="brand__copy">
            <strong>concilia</strong>
            <small>ERP · Banco</small>
          </span>
        </a>
        <nav aria-label="Navegação principal">
          <a href="#fluxo">Nova conciliação</a>
          <a href="#resultado">Resultado</a>
        </nav>
        <span
          className={
            MODO_LOCAL ? "local-badge" : "local-badge local-badge--hospedado"
          }
        >
          <i />
          {MODO_LOCAL ? "Ambiente local" : "Ambiente hospedado"}
        </span>
      </header>

      <main id="conteudo">
        <section className="hero hero--visual" id="inicio">
          <h1 className="hero__title">
            <span>Bank</span>
            <strong>Conciliation</strong>
          </h1>
          <div
            className="reconciliation-signal reconciliation-signal--visual"
            role="img"
            aria-label={
              MODO_LOCAL
                ? "Fluxo visual entre o ERP, a conciliação local e o banco"
                : "Fluxo visual entre o ERP, a conciliação no servidor configurado e o banco"
            }
          >
            <div className="signal-source signal-source--erp">
              <span>
                <BuildingIcon />
              </span>
              <strong>ERP</strong>
            </div>
            <div className="signal-line" aria-hidden="true">
              <i />
              <i />
            </div>
            <div className="signal-core">
              <span className="signal-core__ring" />
              <span className="signal-core__mark">
                <BrandMark />
              </span>
            </div>
            <div className="signal-line signal-line--right" aria-hidden="true">
              <i />
              <i />
            </div>
            <div className="signal-source signal-source--bank">
              <span>
                <BankIcon />
              </span>
              <strong>Banco</strong>
            </div>
          </div>

          {MODO_LOCAL ? (
            <p className="local-notice">
              <strong>Modo local</strong>
              Os arquivos são processados neste computador. O sistema funciona
              enquanto o servidor local estiver aberto.
            </p>
          ) : (
            <p className="local-notice local-notice--hospedado">
              <strong>Modo hospedado</strong>
              Os arquivos selecionados são enviados ao servidor de processamento
              configurado para esta versão. Aguarde a conclusão e baixe o
              Resultado.xlsx ao final.
              <span className="local-notice__aviso">
                Como ainda não há autenticação individual, utilize apenas
                arquivos sintéticos ou previamente autorizados.
              </span>
            </p>
          )}
        </section>

        <section className="workflow-section" id="fluxo">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Nova execução</p>
              <h2>Selecione os arquivos do período</h2>
            </div>
            <ol className="step-list" aria-label="Etapas da conciliação">
              <li className={erpFile && bankFile ? "is-complete" : "is-active"}>
                <span>1</span> Arquivos
              </li>
              <li className={isProcessing ? "is-active" : ""}>
                <span>2</span> Processamento
              </li>
              <li className={result ? "is-complete" : ""}>
                <span>3</span> Resultado
              </li>
            </ol>
          </div>

          <div className="upload-grid">
            <UploadZone
              kind="erp"
              title="Relatório do ERP"
              description="Contas a pagar exportadas do sistema ERP"
              accept=".xlsx,.xls"
              file={erpFile}
              onSelect={selectFile}
              onRemove={removeFile}
            />
            <UploadZone
              kind="bank"
              title="Extrato do banco"
              description="Débitos bancários do mesmo período"
              accept=".ofx,.xlsx,.xls"
              file={bankFile}
              onSelect={selectFile}
              onRemove={removeFile}
            />
          </div>

          <div className="execution-bar">
            <div className="execution-rule">
              <span className="execution-rule__icon">
                <CheckIcon />
              </span>
              <span>
                <strong>Regra central</strong>
                <small>
                  Somente lançamentos com o mesmo valor absoluto e a mesma data
                  podem conciliar.
                </small>
              </span>
            </div>
            <button
              className="primary-action"
              type="button"
              disabled={!erpFile || !bankFile || isProcessing}
              onClick={executeReconciliation}
            >
              {isProcessing ? (
                <>
                  <span className="spinner" />
                  Conciliando
                </>
              ) : (
                <>
                  Executar conciliação
                  <ArrowIcon />
                </>
              )}
            </button>
          </div>

          <div
            className={`processing-panel ${isProcessing ? "is-visible" : ""}`}
            aria-live="polite"
            aria-hidden={!isProcessing}
          >
            <div className="processing-panel__copy">
              <span className="processing-orbit">
                <BrandMark />
              </span>
              <span>
                <strong>{processingMessages[processingStep]}</strong>
                <small>
                  O arquivo final será liberado assim que todas as verificações
                  terminarem.
                </small>
              </span>
            </div>
            <div className="processing-track">
              <i
                style={{
                  transform: `scaleX(${
                    (processingStep + 1) / processingMessages.length
                  })`,
                }}
              />
            </div>
          </div>

          {formError && (
            <div className="form-error" role="alert">
              <ReviewIcon />
              <span>
                <strong>Verifique esta execução</strong>
                {formError}
              </span>
            </div>
          )}
        </section>

        <section className="results-section" id="resultado">
          <div className="section-heading section-heading--results">
            <div>
              <p className="eyebrow">Quadro detalhado de conciliação</p>
              <h2>Resultado da execução</h2>
              <p>{periodLabel}</p>
            </div>
            {result && (
              <button
                type="button"
                className="download-button"
                onClick={downloadResult}
                disabled={isDownloading}
              >
                <DownloadIcon />
                {isDownloading ? "Preparando planilha…" : "Baixar planilha final"}
              </button>
            )}
          </div>

          <div className={`metric-grid ${result ? "" : "is-empty"}`}>
            <MetricCard
              tone="gestao"
              icon={<BuildingIcon />}
              label="Total na Gestão"
              value={result ? formatCurrency(result.indicadores.totalGestao) : "—"}
              detail={
                result
                  ? `${result.entradas.linhasGestao} lançamentos lidos`
                  : "Aguardando o relatório"
              }
            />
            <MetricCard
              tone="banco"
              icon={<BankIcon />}
              label="Total no banco"
              value={result ? formatCurrency(result.indicadores.totalBanco) : "—"}
              detail={
                result
                  ? `${result.entradas.linhasBanco} débitos considerados`
                  : "Aguardando o extrato"
              }
            />
            <MetricCard
              tone="success"
              icon={<CheckIcon />}
              label="Conciliado"
              value={
                result
                  ? `${result.indicadores.conciliado.quantidade} · ${formatPercent(
                      result.indicadores.conciliado.percentual
                    )}`
                  : "—"
              }
              detail="Correspondências confirmadas"
            />
            <MetricCard
              tone="review"
              icon={<ReviewIcon />}
              label="Revisão manual"
              value={
                result
                  ? `${
                      result.indicadores.revisaoManual.quantidade
                    } · ${formatPercent(
                      result.indicadores.revisaoManual.percentual
                    )}`
                  : "—"
              }
              detail="Exige avaliação humana"
            />
            <MetricCard
              tone="danger"
              icon={<BankIcon />}
              label="Somente no banco"
              value={
                result
                  ? `${
                      result.indicadores.somenteBanco.quantidade
                    } · ${formatPercent(
                      result.indicadores.somenteBanco.percentual
                    )}`
                  : "—"
              }
              detail="Sem lançamento correspondente"
            />
          </div>

          <div className="analysis-panel">
            <div className="analysis-panel__heading">
              <div>
                <span className="analysis-panel__icon">
                  <ReviewIcon />
                </span>
                <span>
                  <h3>Itens pendentes de análise</h3>
                  <p>
                    {result
                      ? `${result.pendentesTotal} registro${
                          result.pendentesTotal === 1 ? "" : "s"
                        } precisa${
                          result.pendentesTotal === 1 ? "" : "m"
                        } de atenção`
                      : "A tabela será preenchida após a conciliação"}
                  </p>
                </span>
              </div>
              {result && (
                <div className="analysis-summary">
                  <span>
                    <small>Não encontrados</small>
                    <strong>
                      {result.indicadores.naoEncontradoBanco.quantidade}
                    </strong>
                  </span>
                  <span>
                    <small>Prévia carregada</small>
                    <strong>
                      {result.pendentesExibidos}/{result.pendentesTotal}
                    </strong>
                  </span>
                </div>
              )}
            </div>

            {result ? (
              <>
                <div className="table-toolbar">
                  <label className="search-field">
                    <SearchIcon />
                    <span className="visually-hidden">Buscar pendência</span>
                    <input
                      type="search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Buscar favorecido, motivo ou data"
                    />
                  </label>
                  <div className="filter-group" aria-label="Filtrar por status">
                    {[
                      "Todos",
                      "Revisão Manual",
                      "Não encontrado no banco",
                      "Somente banco",
                    ].map((status) => (
                      <button
                        type="button"
                        key={status}
                        className={statusFilter === status ? "is-active" : ""}
                        aria-pressed={statusFilter === status}
                        onClick={() => setStatusFilter(status)}
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Data</th>
                        <th>Origem</th>
                        <th>Favorecido ou descrição</th>
                        <th className="numeric">Valor na Gestão</th>
                        <th className="numeric">Valor no banco</th>
                        <th>Status</th>
                        <th>Motivo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visiblePending.length ? (
                        visiblePending.map((item, index) => (
                          <tr
                            key={`${item.data}-${item.favorecido}-${index}`}
                          >
                            <td className="date-cell">{formatDate(item.data)}</td>
                            <td>{item.origem}</td>
                            <td className="description-cell">
                              {item.favorecido || "Sem descrição"}
                            </td>
                            <td className="numeric">
                              {formatCurrency(item.valorGestao)}
                            </td>
                            <td className="numeric">
                              {formatCurrency(item.valorBanco)}
                            </td>
                            <td>
                              <span
                                className={`status-pill status-pill--${
                                  item.status === "Revisão Manual"
                                    ? "review"
                                    : item.status === "Somente banco"
                                      ? "danger"
                                      : "neutral"
                                }`}
                              >
                                {item.status}
                              </span>
                            </td>
                            <td className="reason-cell">{item.motivo}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={7}>
                            <div className="no-results">
                              <SearchIcon />
                              <strong>Nenhum item neste filtro</strong>
                              <span>
                                Limpe a busca ou selecione outro status.
                              </span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="table-footer">
                  <span>
                    Mostrando{" "}
                    {visiblePending.length
                      ? (page - 1) * PAGE_SIZE + 1
                      : 0}
                    –
                    {Math.min(page * PAGE_SIZE, filteredPending.length)} de{" "}
                    {filteredPending.length}
                  </span>
                  <div className="pagination">
                    <button
                      type="button"
                      disabled={page === 1}
                      onClick={() => setPage((current) => current - 1)}
                    >
                      Anterior
                    </button>
                    <span>
                      {page} / {totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={page === totalPages}
                      onClick={() => setPage((current) => current + 1)}
                    >
                      Próxima
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="analysis-empty">
                <span className="analysis-empty__visual">
                  <i />
                  <i />
                  <i />
                  <SearchIcon />
                </span>
                <h3>Pronto para a primeira conciliação</h3>
                <p>
                  Adicione os dois arquivos acima. As exceções aparecerão aqui
                  com data, valores, status e motivo.
                </p>
                <a href="#fluxo">
                  Selecionar arquivos <ArrowIcon />
                </a>
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="app-footer">
        <div className="brand brand--footer">
          <span className="brand__mark">
            <BrandMark />
          </span>
          <span className="brand__copy">
            <strong>concilia</strong>
            <small>
              {MODO_LOCAL
                ? "Processamento no seu computador"
                : "Processamento no servidor configurado"}
            </small>
          </span>
        </div>
        <p>
          {MODO_LOCAL
            ? "Os arquivos são processados localmente e não são enviados para uma hospedagem externa."
            : "Os arquivos enviados são processados no servidor configurado para esta versão hospedada."}
        </p>
        <span>Regra de data: 0 dia de tolerância</span>
      </footer>
    </>
  );
}
