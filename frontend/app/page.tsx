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
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  Download,
  FileText,
  Landmark,
  Search,
  Upload,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";
import { RainbowButton } from "@/components/ui/rainbow-button";
import {
  baixarResultado,
  enviarConciliacao,
  type PendingItem,
  type ReconciliationResult,
} from "../lib/api";

type UploadKind = "erp" | "bank";

const PAGE_SIZE = 8;

const processingMessages = [
  "Lendo a estrutura dos arquivos",
  "Aplicando a regra de data exata",
  "Comparando valores e descrições",
  "Fechando lotes e duplicidades",
  "Preparando a planilha final",
];

function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M5 8.5A3.5 3.5 0 0 1 8.5 5h15A3.5 3.5 0 0 1 27 8.5v15a3.5 3.5 0 0 1-3.5 3.5h-15A3.5 3.5 0 0 1 5 23.5v-15Z" />
      <path d="M10 11h12M10 16h7M10 21h12" />
      <path d="m20 14 2.5 2.5L20 19" />
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
  icon,
  file,
  onSelect,
  onRemove,
}: {
  kind: UploadKind;
  title: string;
  description: string;
  accept: string;
  icon: ReactNode;
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
    <div
      className={cn(
        "rounded-2xl border border-black/10 bg-black/[0.03] p-5 backdrop-blur-md transition-colors dark:border-white/10 dark:bg-white/[0.04]",
        file && "border-cyan-500/40 dark:border-cyan-400/30",
      )}
    >
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-black/5 text-cyan-600 dark:bg-white/5 dark:text-cyan-300">
          {icon}
        </span>
        <span>
          <strong className="block text-sm font-semibold text-zinc-900 dark:text-white">{title}</strong>
          <small className="text-xs text-zinc-500 dark:text-zinc-400">{description}</small>
        </span>
      </div>

      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-black/15 px-4 py-8 text-center transition-colors dark:border-white/15",
          dragActive && "border-cyan-500/60 bg-cyan-500/5 dark:border-cyan-400/60",
        )}
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
          <div className="flex w-full items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-300">
              <FileText className="h-5 w-5" />
            </span>
            <span className="min-w-0 flex-1 text-left">
              <strong title={file.name} className="block truncate text-sm text-zinc-900 dark:text-white">
                {file.name}
              </strong>
              <small className="text-xs text-zinc-500 dark:text-zinc-400">
                {formatFileSize(file.size)} · pronto para processar
              </small>
            </span>
            <button
              type="button"
              onClick={() => onRemove(kind)}
              aria-label={`Remover ${file.name}`}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-zinc-500 transition-colors hover:bg-black/10 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <>
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/5 text-zinc-500 dark:bg-white/5 dark:text-zinc-400">
              <Upload className="h-5 w-5" />
            </span>
            <strong className="text-sm font-semibold text-zinc-900 dark:text-white">Arraste o arquivo aqui</strong>
            <span className="text-xs text-zinc-500">ou selecione no computador</span>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="mt-1 rounded-full border border-black/10 bg-black/5 px-4 py-1.5 text-xs font-semibold text-zinc-700 transition-colors hover:bg-black/10 dark:border-white/10 dark:bg-white/5 dark:text-zinc-200 dark:hover:bg-white/10"
            >
              Selecionar arquivo
            </button>
          </>
        )}
        <input
          ref={inputRef}
          className="sr-only"
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

const METRIC_TONE_STYLES: Record<
  "gestao" | "banco" | "success" | "review" | "danger",
  string
> = {
  gestao: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-300",
  banco: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-300",
  success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
  review: "bg-amber-500/10 text-amber-600 dark:text-amber-300",
  danger: "bg-rose-500/10 text-rose-600 dark:text-rose-300",
};

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
    <article className="rounded-2xl border border-black/10 bg-black/[0.02] p-4 dark:border-white/10 dark:bg-white/5">
      <span
        className={cn(
          "mb-3 flex h-9 w-9 items-center justify-center rounded-lg",
          METRIC_TONE_STYLES[tone],
        )}
      >
        {icon}
      </span>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <strong className="mt-1 block text-lg font-semibold text-zinc-900 dark:text-white">{value}</strong>
      <small className="text-xs text-zinc-400 dark:text-zinc-500">{detail}</small>
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
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-cyan-500 focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-zinc-950"
      >
        Ir para o conteúdo
      </a>

      <header className="sticky top-3 z-50 mx-auto flex w-[min(1240px,calc(100%-2rem))] items-center justify-between gap-6 rounded-2xl border border-black/10 bg-white/70 px-5 py-3 backdrop-blur-xl dark:border-white/10 dark:bg-zinc-950/70">
        <a
          className="flex items-center gap-2.5"
          href="#inicio"
          aria-label="Conciliador Bancário — início"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-500/10 text-cyan-600 dark:text-cyan-300">
            <BrandMark className="h-5 w-5" />
          </span>
          <span className="flex flex-col leading-none">
            <strong className="text-sm font-bold tracking-tight text-zinc-900 dark:text-white">concilia</strong>
            <small className="text-[10px] uppercase tracking-wide text-zinc-500">
              ERP · Banco
            </small>
          </span>
        </a>
        <div className="flex items-center gap-1">
          <nav aria-label="Navegação principal" className="hidden items-center gap-1 sm:flex">
            <a
              href="#fluxo"
              className="rounded-lg px-3 py-2 text-sm font-medium text-zinc-500 transition-colors hover:bg-black/5 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-white"
            >
              Nova conciliação
            </a>
            <a
              href="#resultado"
              className="rounded-lg px-3 py-2 text-sm font-medium text-zinc-500 transition-colors hover:bg-black/5 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/5 dark:hover:text-white"
            >
              Resultado
            </a>
          </nav>
          <ThemeToggle />
        </div>
      </header>

      <main id="conteudo">
        <section id="inicio" className="mx-auto mt-16 flex w-[min(1240px,calc(100%-2rem))] flex-col items-center gap-12 text-center sm:mt-24">
          <h1 className="flex flex-col items-center gap-2">
            <span className="text-xl font-extrabold uppercase tracking-[0.4em] text-cyan-600 dark:text-cyan-400 sm:text-2xl">
              Bank
            </span>
            <strong className="text-4xl font-extrabold uppercase tracking-tight text-zinc-900 dark:text-white sm:text-5xl lg:text-6xl">
              Conciliation
            </strong>
          </h1>

          <div
            role="img"
            aria-label="Fluxo visual entre o ERP, a conciliação e o banco"
            className="flex w-full max-w-xl items-center justify-center gap-4 sm:gap-8"
          >
            <div className="flex flex-col items-center gap-2">
              <span className="flex h-16 w-16 items-center justify-center rounded-2xl border border-black/10 bg-black/[0.03] text-cyan-600 shadow-[0_0_30px_rgba(34,211,238,0.15)] dark:border-white/10 dark:bg-white/5 dark:text-cyan-300">
                <Building2 className="h-7 w-7" />
              </span>
              <strong className="text-sm font-semibold text-zinc-600 dark:text-zinc-300">ERP</strong>
            </div>

            <div className="relative h-0.5 flex-1 bg-blue-500 dark:bg-cyan-400/60">
              <span className="absolute left-1/3 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500 dark:bg-cyan-400" />
              <span className="absolute left-2/3 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500 dark:bg-cyan-400" />
            </div>

            <div className="relative flex h-20 w-20 items-center justify-center">
              <span className="absolute -inset-2 rounded-full border-2 border-dashed border-blue-200 dark:border-cyan-400/40" />
              <span className="absolute -top-0.5 right-2.5 h-2 w-2 rounded-full bg-blue-500 dark:bg-cyan-400" />
              <span className="absolute inset-0 rounded-full bg-white shadow-[0_10px_30px_rgba(15,23,42,0.12)] dark:bg-zinc-900 dark:shadow-[0_0_40px_rgba(34,211,238,0.25)]" />
              <span className="relative flex h-12 w-12 items-center justify-center rounded-2xl bg-[#08264b] text-white">
                <BrandMark className="h-6 w-6" />
              </span>
            </div>

            <div className="relative h-0.5 flex-1 bg-blue-500 dark:bg-cyan-400/60">
              <span className="absolute left-1/3 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500 dark:bg-cyan-400" />
              <span className="absolute left-2/3 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500 dark:bg-cyan-400" />
            </div>

            <div className="flex flex-col items-center gap-2">
              <span className="flex h-16 w-16 items-center justify-center rounded-2xl border border-black/10 bg-black/[0.03] text-indigo-600 shadow-[0_0_30px_rgba(99,102,241,0.15)] dark:border-white/10 dark:bg-white/5 dark:text-indigo-300">
                <Landmark className="h-7 w-7" />
              </span>
              <strong className="text-sm font-semibold text-zinc-600 dark:text-zinc-300">Banco</strong>
            </div>
          </div>
        </section>

        <section id="fluxo" className="mx-auto mt-20 w-[min(1240px,calc(100%-2rem))]">
          <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-cyan-600 dark:text-cyan-400">
                Nova execução
              </p>
              <h2 className="mt-1 text-3xl font-extrabold text-zinc-900 dark:text-white sm:text-4xl">
                Selecione os arquivos do período
              </h2>
            </div>
            <ol aria-label="Etapas da conciliação" className="flex gap-2 text-xs font-semibold">
              <li
                className={cn(
                  "flex items-center gap-1.5 rounded-full border border-black/10 px-3 py-1.5 dark:border-white/10",
                  erpFile && bankFile
                    ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-600 dark:border-cyan-400/40 dark:text-cyan-300"
                    : "text-zinc-500 dark:text-zinc-400",
                )}
              >
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-black/10 text-[10px] dark:bg-white/10">1</span>
                Arquivos
              </li>
              <li
                className={cn(
                  "flex items-center gap-1.5 rounded-full border border-black/10 px-3 py-1.5 dark:border-white/10",
                  isProcessing
                    ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-600 dark:border-cyan-400/40 dark:text-cyan-300"
                    : "text-zinc-500 dark:text-zinc-400",
                )}
              >
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-black/10 text-[10px] dark:bg-white/10">2</span>
                Processamento
              </li>
              <li
                className={cn(
                  "flex items-center gap-1.5 rounded-full border border-black/10 px-3 py-1.5 dark:border-white/10",
                  result
                    ? "border-cyan-500/40 bg-cyan-500/10 text-cyan-600 dark:border-cyan-400/40 dark:text-cyan-300"
                    : "text-zinc-500 dark:text-zinc-400",
                )}
              >
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-black/10 text-[10px] dark:bg-white/10">3</span>
                Resultado
              </li>
            </ol>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <UploadZone
              kind="erp"
              title="Relatório do ERP"
              description="Contas a pagar exportadas do sistema ERP"
              accept=".xlsx,.xls"
              icon={<Building2 className="h-5 w-5" />}
              file={erpFile}
              onSelect={selectFile}
              onRemove={removeFile}
            />
            <UploadZone
              kind="bank"
              title="Extrato do banco"
              description="Débitos bancários do mesmo período"
              accept=".ofx,.xlsx,.xls"
              icon={<Landmark className="h-5 w-5" />}
              file={bankFile}
              onSelect={selectFile}
              onRemove={removeFile}
            />
          </div>

          <div className="mt-6 flex flex-col items-stretch gap-4 rounded-2xl border border-black/10 bg-black/[0.03] p-5 backdrop-blur-md dark:border-white/10 dark:bg-white/[0.04] sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-300">
                <CheckCircle2 className="h-4 w-4" />
              </span>
              <span>
                <strong className="block text-sm font-semibold text-zinc-900 dark:text-white">Regra central</strong>
                <small className="text-xs text-zinc-500 dark:text-zinc-400">
                  Somente lançamentos com o mesmo valor absoluto e a mesma data podem conciliar.
                </small>
              </span>
            </div>
            <RainbowButton
              className="gap-2"
              type="button"
              disabled={!erpFile || !bankFile || isProcessing}
              onClick={executeReconciliation}
            >
              {isProcessing ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-current/30 border-t-current" />
                  Conciliando
                </>
              ) : (
                <>
                  Executar conciliação
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </RainbowButton>
          </div>

          <div
            className={cn(
              "mt-4 overflow-hidden rounded-2xl border border-black/10 bg-black/[0.02] transition-all duration-500 dark:border-white/10 dark:bg-zinc-950/60",
              isProcessing ? "max-h-40 p-5 opacity-100" : "max-h-0 border-0 p-0 opacity-0",
            )}
            aria-live="polite"
            aria-hidden={!isProcessing}
          >
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-cyan-500/10 text-cyan-600 dark:text-cyan-300">
                <BrandMark className="h-5 w-5 animate-spin [animation-duration:2.4s]" />
              </span>
              <span>
                <strong className="block text-sm font-semibold text-zinc-900 dark:text-white">
                  {processingMessages[processingStep]}
                </strong>
                <small className="text-xs text-zinc-500 dark:text-zinc-400">
                  O arquivo final será liberado assim que todas as verificações terminarem.
                </small>
              </span>
            </div>
            <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
              <div
                className="h-full origin-left rounded-full bg-cyan-500 transition-transform duration-500 dark:bg-cyan-400"
                style={{
                  transform: `scaleX(${
                    (processingStep + 1) / processingMessages.length
                  })`,
                }}
              />
            </div>
          </div>

          {formError && (
            <div role="alert" className="mt-4 flex items-start gap-3 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-4 text-rose-700 dark:text-rose-200">
              <AlertTriangle className="h-5 w-5 shrink-0" />
              <span>
                <strong className="block text-sm font-semibold text-rose-800 dark:text-rose-100">Verifique esta execução</strong>
                <span className="text-sm">{formError}</span>
              </span>
            </div>
          )}
        </section>

        <section id="resultado" className="mx-auto mb-24 mt-20 w-[min(1240px,calc(100%-2rem))]">
          <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-cyan-600 dark:text-cyan-400">
                Quadro detalhado de conciliação
              </p>
              <h2 className="mt-1 text-3xl font-extrabold text-zinc-900 dark:text-white sm:text-4xl">Resultado da execução</h2>
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">{periodLabel}</p>
            </div>
            {result && (
              <button
                type="button"
                className="inline-flex items-center justify-center gap-2 rounded-full border border-black/10 bg-black/5 px-5 py-2.5 text-sm font-semibold text-zinc-900 transition-colors hover:bg-black/10 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/10 dark:bg-white/5 dark:text-white dark:hover:bg-white/10"
                onClick={downloadResult}
                disabled={isDownloading}
              >
                <Download className="h-4 w-4" />
                {isDownloading ? "Preparando planilha…" : "Baixar planilha final"}
              </button>
            )}
          </div>

          <div
            className={cn(
              "grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5",
              !result && "opacity-40",
            )}
          >
            <MetricCard
              tone="gestao"
              icon={<Building2 className="h-5 w-5" />}
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
              icon={<Landmark className="h-5 w-5" />}
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
              icon={<CheckCircle2 className="h-5 w-5" />}
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
              icon={<AlertTriangle className="h-5 w-5" />}
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
              icon={<Landmark className="h-5 w-5" />}
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

          <div className="mt-8 rounded-3xl border border-black/10 bg-black/[0.015] p-6 backdrop-blur-md dark:border-white/10 dark:bg-white/[0.03]">
            <div className="flex flex-col gap-4 border-b border-black/10 pb-5 dark:border-white/10 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-300">
                  <AlertTriangle className="h-5 w-5" />
                </span>
                <span>
                  <h3 className="text-base font-semibold text-zinc-900 dark:text-white">Itens pendentes de análise</h3>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400">
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
                <div className="flex gap-6 text-right">
                  <span>
                    <small className="block text-xs text-zinc-400 dark:text-zinc-500">Não encontrados</small>
                    <strong className="text-lg font-semibold text-zinc-900 dark:text-white">
                      {result.indicadores.naoEncontradoBanco.quantidade}
                    </strong>
                  </span>
                  <span>
                    <small className="block text-xs text-zinc-400 dark:text-zinc-500">Prévia carregada</small>
                    <strong className="text-lg font-semibold text-zinc-900 dark:text-white">
                      {result.pendentesExibidos}/{result.pendentesTotal}
                    </strong>
                  </span>
                </div>
              )}
            </div>

            {result ? (
              <>
                <div className="flex flex-col gap-3 py-5 sm:flex-row sm:items-center sm:justify-between">
                  <label className="flex items-center gap-2 rounded-full border border-black/10 bg-black/5 px-4 py-2 text-sm text-zinc-700 focus-within:border-cyan-500/50 dark:border-white/10 dark:bg-white/5 dark:text-zinc-300 dark:focus-within:border-cyan-400/50 sm:w-72">
                    <Search className="h-4 w-4 text-zinc-400 dark:text-zinc-500" />
                    <span className="sr-only">Buscar pendência</span>
                    <input
                      type="search"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Buscar favorecido, motivo ou data"
                      className="w-full bg-transparent text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none dark:text-white dark:placeholder:text-zinc-500"
                    />
                  </label>
                  <div aria-label="Filtrar por status" className="flex flex-wrap gap-2">
                    {[
                      "Todos",
                      "Revisão Manual",
                      "Não encontrado no banco",
                      "Somente banco",
                    ].map((status) => (
                      <button
                        type="button"
                        key={status}
                        aria-pressed={statusFilter === status}
                        onClick={() => setStatusFilter(status)}
                        className={cn(
                          "rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                          statusFilter === status
                            ? "border-cyan-500/50 bg-cyan-500 text-zinc-950"
                            : "border-black/10 bg-black/5 text-zinc-500 hover:text-zinc-900 dark:border-white/10 dark:bg-white/5 dark:text-zinc-400 dark:hover:text-white",
                        )}
                      >
                        {status}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="-mx-6 overflow-x-auto px-6">
                  <table className="w-full min-w-[880px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="text-xs uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                        <th className="border-b border-black/10 py-3 pr-4 font-medium dark:border-white/10">Data</th>
                        <th className="border-b border-black/10 py-3 pr-4 font-medium dark:border-white/10">Origem</th>
                        <th className="border-b border-black/10 py-3 pr-4 font-medium dark:border-white/10">
                          Favorecido ou descrição
                        </th>
                        <th className="border-b border-black/10 py-3 pr-4 text-right font-medium dark:border-white/10">
                          Valor na Gestão
                        </th>
                        <th className="border-b border-black/10 py-3 pr-4 text-right font-medium dark:border-white/10">
                          Valor no banco
                        </th>
                        <th className="border-b border-black/10 py-3 pr-4 font-medium dark:border-white/10">Status</th>
                        <th className="border-b border-black/10 py-3 font-medium dark:border-white/10">Motivo</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-black/5 dark:divide-white/5">
                      {visiblePending.length ? (
                        visiblePending.map((item, index) => (
                          <tr key={`${item.data}-${item.favorecido}-${index}`} className="text-zinc-600 dark:text-zinc-300">
                            <td className="py-3 pr-4 font-mono text-xs text-zinc-500 dark:text-zinc-400">
                              {formatDate(item.data)}
                            </td>
                            <td className="py-3 pr-4">{item.origem}</td>
                            <td className="py-3 pr-4 text-zinc-900 dark:text-white">
                              {item.favorecido || "Sem descrição"}
                            </td>
                            <td className="py-3 pr-4 text-right font-mono">
                              {formatCurrency(item.valorGestao)}
                            </td>
                            <td className="py-3 pr-4 text-right font-mono">
                              {formatCurrency(item.valorBanco)}
                            </td>
                            <td className="py-3 pr-4">
                              <span
                                className={cn(
                                  "inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold",
                                  item.status === "Revisão Manual"
                                    ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                                    : item.status === "Somente banco"
                                      ? "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300"
                                      : "border-black/10 bg-black/5 text-zinc-600 dark:border-white/10 dark:bg-white/5 dark:text-zinc-300",
                                )}
                              >
                                {item.status}
                              </span>
                            </td>
                            <td className="py-3 text-zinc-500 dark:text-zinc-400">{item.motivo}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={7} className="py-12 text-center">
                            <div className="flex flex-col items-center gap-2 text-zinc-400 dark:text-zinc-500">
                              <Search className="h-6 w-6" />
                              <strong className="text-sm text-zinc-600 dark:text-zinc-300">Nenhum item neste filtro</strong>
                              <span className="text-xs">Limpe a busca ou selecione outro status.</span>
                            </div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                <div className="flex flex-col gap-3 border-t border-black/10 pt-5 dark:border-white/10 sm:flex-row sm:items-center sm:justify-between">
                  <span className="text-xs text-zinc-400 dark:text-zinc-500">
                    Mostrando{" "}
                    {visiblePending.length
                      ? (page - 1) * PAGE_SIZE + 1
                      : 0}
                    –
                    {Math.min(page * PAGE_SIZE, filteredPending.length)} de{" "}
                    {filteredPending.length}
                  </span>
                  <div className="flex items-center gap-3 text-sm">
                    <button
                      type="button"
                      disabled={page === 1}
                      onClick={() => setPage((current) => current - 1)}
                      className="rounded-full border border-black/10 px-3 py-1.5 text-xs font-semibold text-zinc-600 transition-colors hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:text-white"
                    >
                      Anterior
                    </button>
                    <span className="text-xs text-zinc-400 dark:text-zinc-500">
                      {page} / {totalPages}
                    </span>
                    <button
                      type="button"
                      disabled={page === totalPages}
                      onClick={() => setPage((current) => current + 1)}
                      className="rounded-full border border-black/10 px-3 py-1.5 text-xs font-semibold text-zinc-600 transition-colors hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:text-zinc-300 dark:hover:text-white"
                    >
                      Próxima
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center gap-3 py-16 text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-full border border-black/10 bg-black/5 text-cyan-600 dark:border-white/10 dark:bg-white/5 dark:text-cyan-300">
                  <Search className="h-6 w-6" />
                </span>
                <h3 className="text-base font-semibold text-zinc-900 dark:text-white">Pronto para a primeira conciliação</h3>
                <p className="max-w-sm text-sm text-zinc-500 dark:text-zinc-400">
                  Adicione os dois arquivos acima. As exceções aparecerão aqui
                  com data, valores, status e motivo.
                </p>
                <a
                  href="#fluxo"
                  className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold text-cyan-600 hover:text-cyan-700 dark:text-cyan-300 dark:hover:text-cyan-200"
                >
                  Selecionar arquivos <ArrowRight className="h-4 w-4" />
                </a>
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="mx-auto mb-10 flex w-[min(1240px,calc(100%-2rem))] flex-col items-center justify-between gap-3 border-t border-black/10 pt-6 text-xs text-zinc-400 dark:border-white/10 dark:text-zinc-500 sm:flex-row">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-cyan-500/10 text-cyan-600 dark:text-cyan-300">
            <BrandMark className="h-3.5 w-3.5" />
          </span>
          <span className="font-semibold text-zinc-600 dark:text-zinc-300">concilia</span>
          <span>· ERP · Banco</span>
        </div>
        <span>Regra de data: 0 dia de tolerância</span>
      </footer>
    </>
  );
}
