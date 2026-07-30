import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const RUN_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> }
) {
  const { runId } = await context.params;
  if (!RUN_ID_PATTERN.test(runId)) {
    return Response.json({ error: "Resultado inválido." }, { status: 400 });
  }

  try {
    const filePath = path.join(
      process.cwd(),
      ".web-runtime",
      runId,
      "Resultado.xlsx"
    );
    const file = await readFile(filePath);
    return new Response(new Uint8Array(file), {
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition":
          'attachment; filename="Resultado_conciliacao.xlsx"',
        "Cache-Control": "private, no-store",
      },
    });
  } catch {
    return Response.json(
      { error: "O arquivo desta execução não está mais disponível." },
      { status: 404 }
    );
  }
}
