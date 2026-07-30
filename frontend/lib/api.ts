/**
 * Acesso ao backend Python do Conciliador Bancário.
 *
 * O navegador fala direto com a API (nenhuma rota do Next.js no caminho),
 * então nem o limite de 4,5 MB por request nem o timeout das funções da
 * Vercel se aplicam aos arquivos enviados.
 */

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(
  /\/+$/,
  ""
);

const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export type Indicator = {
  quantidade: number;
  percentual: number;
};

export type PendingItem = {
  data: string | null;
  origem: string;
  favorecido: string;
  valorGestao: number | null;
  valorBanco: number | null;
  status: string;
  motivo: string;
};

export type ReconciliationResult = {
  runId: string;
  downloadUrl: string;
  files: {
    erp: string;
    bank: string;
  };
  periodo: {
    inicio: string | null;
    fim: string | null;
  };
  entradas: {
    linhasGestao: number;
    linhasBanco: number;
  };
  indicadores: {
    totalGestao: number;
    totalBanco: number;
    conciliado: Indicator;
    revisaoManual: Indicator;
    somenteBanco: Indicator;
    naoEncontradoBanco: Indicator;
    totalLinhas: number;
  };
  pendentes: PendingItem[];
  pendentesTotal: number;
  pendentesExibidos: number;
};

function authHeaders(): HeadersInit {
  return API_TOKEN ? { "X-API-Token": API_TOKEN } : {};
}

/**
 * Traduz uma falha de rede na mensagem que o usuário precisa ver.
 *
 * Sem isto, um backend fora do ar ou uma origem não liberada no CORS chegam
 * na tela como "Failed to fetch", que não diz o que fazer.
 */
function erroDeRede(): Error {
  return new Error(
    `Não foi possível falar com o servidor de conciliação (${API_URL}). ` +
      "Verifique se ele está no ar e se esta origem está liberada no CORS."
  );
}

export async function enviarConciliacao(
  erpFile: File,
  bankFile: File
): Promise<ReconciliationResult> {
  const formData = new FormData();
  formData.append("erp", erpFile);
  formData.append("bank", bankFile);

  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/reconcile`, {
      method: "POST",
      headers: authHeaders(),
      body: formData,
    });
  } catch {
    throw erroDeRede();
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const mensagem =
      payload?.error || "Não foi possível executar a conciliação.";
    throw new Error(payload?.detail ? `${mensagem} ${payload.detail}` : mensagem);
  }

  return payload as ReconciliationResult;
}

/**
 * Baixa o Resultado.xlsx.
 *
 * Precisa ser fetch + Blob (e não um link direto): um `<a href>` não envia o
 * header do token.
 */
export async function baixarResultado(downloadUrl: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${downloadUrl}`, {
      headers: authHeaders(),
    });
  } catch {
    throw erroDeRede();
  }

  if (!response.ok) {
    throw new Error("O arquivo desta execução não está mais disponível.");
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = "Resultado_conciliacao.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}
