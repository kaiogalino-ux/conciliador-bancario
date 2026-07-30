<#
.SYNOPSIS
    Encerra o backend e o frontend locais do Conciliador Bancario.

.DESCRIPTION
    Encerra SOMENTE os processos deste projeto. Identifica os alvos de duas
    formas complementares:

      1. pelos PIDs registrados em .dev-runtime\processos.json na inicializacao;
      2. por quem esta escutando nas portas 8000 e 3000, conferindo antes que o
         processo pertence a este projeto (caminho do .venv ou de frontend\).

    Nunca usa taskkill /IM python.exe nem /IM node.exe: outros processos Python
    ou Node da maquina ficam intactos. Um processo que escute na porta mas nao
    pertenca ao projeto e apenas reportado, nunca encerrado.

.EXAMPLE
    .\parar_conciliador.ps1
#>

[CmdletBinding()]
param(
    [int]$PortaBackend = 8000,
    [int]$PortaFrontend = 3000
)

$ErrorActionPreference = "Stop"

$Raiz = $PSScriptRoot
$PastaEstado = Join-Path $Raiz ".dev-runtime"
$ArquivoEstado = Join-Path $PastaEstado "processos.json"

function Escrever-Ok($texto) { Write-Host "  OK  $texto" -ForegroundColor Green }
function Escrever-Aviso($texto) { Write-Host "  --  $texto" -ForegroundColor Yellow }

# Um processo so e alvo se a linha de comando apontar para dentro deste projeto.
function Pertence-Ao-Projeto($processo) {
    if (-not $processo -or -not $processo.CommandLine) { return $false }
    $cl = $processo.CommandLine
    return ($cl -like "*$Raiz*")
}

function Descrever($processo) {
    $cl = if ($processo.CommandLine) { $processo.CommandLine } else { $processo.Name }
    if ($cl.Length -gt 90) { $cl = $cl.Substring(0, 90) + "..." }
    return "PID $($processo.ProcessId) ($($processo.Name)) $cl"
}

# Encerra a arvore de baixo para cima: filhos primeiro, para o pai nao respawnar.
function Encerrar-Arvore([int]$id, [System.Collections.Generic.HashSet[int]]$jaVistos) {
    if (-not $jaVistos.Add($id)) { return }

    Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue |
        ForEach-Object { Encerrar-Arvore $_.ProcessId $jaVistos }

    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $proc) { return }

    Stop-Process -Id $id -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Milliseconds 300
        if (-not (Get-Process -Id $id -ErrorAction SilentlyContinue)) { return }
    }
    # So depois de 3s sem resposta, e apenas neste PID.
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Encerrando o Conciliador Bancario (modo local)" -ForegroundColor White
Write-Host "==============================================" -ForegroundColor DarkGray
Write-Host ""

$alvos = [System.Collections.Generic.List[object]]::new()
$vistos = [System.Collections.Generic.HashSet[int]]::new()

# --- 1) PIDs registrados na inicializacao ---------------------------------

if (Test-Path $ArquivoEstado) {
    try {
        $estado = Get-Content $ArquivoEstado -Raw -Encoding utf8 | ConvertFrom-Json
        foreach ($id in @($estado.janelaBackend, $estado.janelaFrontend)) {
            if (-not $id) { continue }
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
            if ($p -and $vistos.Add([int]$id)) {
                $alvos.Add([pscustomobject]@{ Processo = $p; Origem = "registrado na inicializacao" })
            }
        }
    } catch {
        Escrever-Aviso "Nao foi possivel ler $ArquivoEstado (sera ignorado)."
    }
}

# --- 2) Quem escuta nas portas do projeto ---------------------------------

foreach ($porta in @($PortaBackend, $PortaFrontend)) {
    $conexoes = Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conexoes) {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $p) { continue }

        if (-not (Pertence-Ao-Projeto $p)) {
            Escrever-Aviso "Porta ${porta}: $(Descrever $p)"
            Escrever-Aviso "    nao pertence a este projeto - NAO sera encerrado."
            continue
        }
        if ($vistos.Add([int]$p.ProcessId)) {
            $alvos.Add([pscustomobject]@{ Processo = $p; Origem = "escutando na porta $porta" })
        }
    }
}

if ($alvos.Count -eq 0) {
    Write-Host "  Nada para encerrar - o Conciliador nao esta rodando." -ForegroundColor DarkGray
    if (Test-Path $ArquivoEstado) { Remove-Item $ArquivoEstado -Force -ErrorAction SilentlyContinue }
    Write-Host ""
    exit 0
}

Write-Host "  Processos deste projeto encontrados:" -ForegroundColor Cyan
foreach ($a in $alvos) {
    Write-Host "    $(Descrever $a.Processo)  [$($a.Origem)]"
}
Write-Host ""

$encerrados = [System.Collections.Generic.HashSet[int]]::new()
foreach ($a in $alvos) {
    Encerrar-Arvore ([int]$a.Processo.ProcessId) $encerrados
}

# --- Conferencia ----------------------------------------------------------

$restaram = @()
foreach ($porta in @($PortaBackend, $PortaFrontend)) {
    if (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue) {
        $restaram += $porta
    } else {
        Escrever-Ok "Porta $porta liberada"
    }
}

if (Test-Path $ArquivoEstado) { Remove-Item $ArquivoEstado -Force -ErrorAction SilentlyContinue }

Write-Host ""
if ($restaram.Count -eq 0) {
    Write-Host "Conciliador encerrado." -ForegroundColor Green
} else {
    Write-Host "Ainda ha algo escutando em: $($restaram -join ', ')" -ForegroundColor Yellow
    Write-Host "  Descubra quem e com:" -ForegroundColor Yellow
    Write-Host "      Get-NetTCPConnection -LocalPort $($restaram[0]) -State Listen"
}
Write-Host ""
