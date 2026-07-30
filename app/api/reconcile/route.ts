import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_FILE_SIZE = 30 * 1024 * 1024;
const ERP_EXTENSIONS = new Set([".xlsx", ".xls"]);
const BANK_EXTENSIONS = new Set([".ofx", ".xlsx", ".xls"]);

function safeName(fileName: string, fallback: string) {
  const extension = path.extname(fileName).toLowerCase();
  const baseName = path
    .basename(fileName, extension)
    .normalize("NFKD")
    .replace(/[^\w.-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
  return `${baseName || fallback}${extension}`;
}

function jsonError(message: string, status: number, detail?: string) {
  return Response.json({ error: message, detail }, { status });
}

async function findPython(projectRoot: string) {
  const configured = process.env.PYTHON_EXECUTABLE;
  const candidates = [
    configured,
    process.platform === "win32"
      ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
      : path.join(projectRoot, ".venv", "bin", "python"),
    process.platform === "win32" ? "python.exe" : "python3",
  ].filter(Boolean) as string[];

  for (const candidate of candidates) {
    if (!path.isAbsolute(candidate)) return candidate;
    try {
      await access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error(
    "Python não encontrado. Ative ou recrie o ambiente virtual .venv."
  );
}

function runPython(
  executable: string,
  args: string[],
  projectRoot: string
): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    execFile(
      executable,
      args,
      {
        cwd: projectRoot,
        encoding: "utf8",
        timeout: 10 * 60 * 1000,
        maxBuffer: 12 * 1024 * 1024,
        windowsHide: true,
        env: {
          ...process.env,
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
        },
      },
      (error, stdout, stderr) => {
        if (error) {
          const reason =
            stderr
              .trim()
              .split(/\r?\n/)
              .filter(Boolean)
              .at(-1) || error.message;
          reject(new Error(reason));
          return;
        }
        resolve({ stdout, stderr });
      }
    );
  });
}

function validateUpload(
  file: FormDataEntryValue | null,
  label: string,
  extensions: Set<string>
): asserts file is File {
  if (!(file instanceof File) || file.size === 0) {
    throw new Error(`Selecione o arquivo ${label}.`);
  }
  const extension = path.extname(file.name).toLowerCase();
  if (!extensions.has(extension)) {
    throw new Error(
      `${label}: formato não aceito. Use ${Array.from(extensions).join(", ")}.`
    );
  }
  if (file.size > MAX_FILE_SIZE) {
    throw new Error(`${label}: o arquivo deve ter no máximo 30 MB.`);
  }
}

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const erpFile = formData.get("erp");
    const bankFile = formData.get("bank");

    validateUpload(erpFile, "da Gestão", ERP_EXTENSIONS);
    validateUpload(bankFile, "do banco", BANK_EXTENSIONS);

    const projectRoot = process.cwd();
    const runId = randomUUID();
    const runRoot = path.join(projectRoot, ".web-runtime", runId);
    const erpDir = path.join(runRoot, "erp");
    const bankDir = path.join(runRoot, "banco");
    const resultPath = path.join(runRoot, "Resultado.xlsx");

    await Promise.all([
      mkdir(erpDir, { recursive: true }),
      mkdir(bankDir, { recursive: true }),
    ]);

    const erpPath = path.join(erpDir, safeName(erpFile.name, "gestao"));
    const bankPath = path.join(bankDir, safeName(bankFile.name, "banco"));
    await Promise.all([
      writeFile(erpPath, Buffer.from(await erpFile.arrayBuffer())),
      writeFile(bankPath, Buffer.from(await bankFile.arrayBuffer())),
    ]);

    const python = await findPython(projectRoot);
    const { stdout } = await runPython(
      python,
      [
        "-m",
        "src.web_runner",
        "--erp-dir",
        erpDir,
        "--banco-dir",
        bankDir,
        "--output",
        resultPath,
      ],
      projectRoot
    );

    const jsonLine = stdout
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)
      .at(-1);
    if (!jsonLine) {
      throw new Error("O conciliador terminou sem devolver o resumo.");
    }

    const result = JSON.parse(jsonLine);
    return Response.json({
      ...result,
      runId,
      downloadUrl: `/api/reconcile/${runId}/download`,
      files: {
        erp: erpFile.name,
        bank: bankFile.name,
      },
    });
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "Não foi possível executar a conciliação.";
    const validationError =
      message.startsWith("Selecione") ||
      message.includes("formato não aceito") ||
      message.includes("no máximo 30 MB");
    return jsonError(
      validationError
        ? message
        : "A conciliação não foi concluída. Verifique os arquivos e tente novamente.",
      validationError ? 400 : 500,
      validationError ? undefined : message.slice(0, 600)
    );
  }
}
