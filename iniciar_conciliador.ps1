<#
.SYNOPSIS
    Sobe o Conciliador Bancario em modo local: backend FastAPI + frontend Next.js.

.DESCRIPTION
    Abre uma janela do PowerShell para cada servico, espera os dois responderem
    e entao abre o navegador. Os PIDs sao registrados em .dev-runtime\ para que
    o parar_conciliador.ps1 encerre exatamente estes processos, e nenhum outro.

    Nada e publicado na internet: os dois servidores escutam apenas em 127.0.0.1.

.EXAMPLE
    .\iniciar_conciliador.ps1
    .\iniciar_conciliador.ps1 -SemNavegador
#>

[CmdletBinding()]
param(
    [int]$PortaBackend = 8000,
    [int]$PortaFrontend = 3000,
    [int]$SegundosLimite = 120,
    [switch]$SemNavegador
)

$ErrorActionPreference = "Stop"

$Raiz = $PSScriptRoot
$Backend = Join-Path $Raiz "backend"
$Frontend = Join-Path $Raiz "frontend"
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$PastaEstado = Join-Path $Raiz ".dev-runtime"
$ArquivoEstado = Join-Path $PastaEstado "processos.json"

function Escrever-Passo($texto) { Write-Host "  $texto" -ForegroundColor Cyan }
function Escrever-Ok($texto) { Write-Host "  OK  $texto" -ForegroundColor Green }
function Escrever-Erro($texto) { Write-Host "  ERRO  $texto" -ForegroundColor Red }

function Testar-Porta([int]$porta) {
    $null -ne (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)
}

function Esperar-Servico([string]$url, [string]$nome, [int]$limite) {
    for ($i = 0; $i -lt $limite; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

Write-Host ""
Write-Host "Conciliador Bancario - modo local" -ForegroundColor White
Write-Host "=================================" -ForegroundColor DarkGray
Write-Host ""

# --- Pre-requisitos -------------------------------------------------------

Escrever-Passo "Verificando o ambiente..."

if (-not (Test-Path $Backend)) {
    Escrever-Erro "Pasta 'backend' nao encontrada em $Raiz."
    Write-Host "  Rode este script de dentro da pasta do projeto."
    exit 1
}

if (-not (Test-Path $Frontend)) {
    Escrever-Erro "Pasta 'frontend' nao encontrada em $Raiz."
    exit 1
}

if (-not (Test-Path $Python)) {
    Escrever-Erro "Ambiente virtual nao encontrado em .venv"
    Write-Host ""
    Write-Host "  Crie o ambiente e instale as dependencias:" -ForegroundColor Yellow
    Write-Host "      python -m venv .venv"
    Write-Host "      .venv\Scripts\activate"
    Write-Host "      pip install -r backend\requirements-dev.txt"
    exit 1
}
Escrever-Ok "Ambiente virtual encontrado (.venv)"

if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Escrever-Erro "Dependencias do frontend nao instaladas (node_modules ausente)."
    Write-Host ""
    Write-Host "  Instale com:" -ForegroundColor Yellow
    Write-Host "      cd frontend"
    Write-Host "      npm install"
    exit 1
}
Escrever-Ok "Dependencias do frontend encontradas (node_modules)"

if (-not (Test-Path (Join-Path $Backend ".env"))) {
    Write-Host "  AVISO  backend\.env nao existe. Copie de backend\.env.example." -ForegroundColor Yellow
}
if (-not (Test-Path (Join-Path $Frontend ".env.local"))) {
    Write-Host "  AVISO  frontend\.env.local nao existe. Copie de frontend\.env.local.example." -ForegroundColor Yellow
}

foreach ($p in @($PortaBackend, $PortaFrontend)) {
    if (Testar-Porta $p) {
        Escrever-Erro "A porta $p ja esta em uso."
        Write-Host "  Rode .\parar_conciliador.ps1 antes, ou descubra quem esta usando:" -ForegroundColor Yellow
        Write-Host "      Get-NetTCPConnection -LocalPort $p -State Listen"
        exit 1
    }
}
Escrever-Ok "Portas $PortaBackend e $PortaFrontend livres"

# --- Inicializacao --------------------------------------------------------

New-Item -ItemType Directory -Force $PastaEstado | Out-Null

Write-Host ""
Escrever-Passo "Iniciando o backend (FastAPI) na porta $PortaBackend..."
$cmdBackend = "Set-Location '$Backend'; " +
              "Write-Host 'Backend FastAPI - http://localhost:$PortaBackend' -ForegroundColor Green; " +
              "Write-Host 'Feche esta janela ou rode parar_conciliador.ps1 para encerrar.'; " +
              "& '$Python' -m uvicorn api.main:app --host 127.0.0.1 --port $PortaBackend"
$procBackend = Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmdBackend -PassThru

Escrever-Passo "Iniciando o frontend (Next.js) na porta $PortaFrontend..."
$cmdFrontend = "Set-Location '$Frontend'; " +
               "Write-Host 'Frontend Next.js - http://localhost:$PortaFrontend' -ForegroundColor Green; " +
               "Write-Host 'Feche esta janela ou rode parar_conciliador.ps1 para encerrar.'; " +
               "npm run dev"
$procFrontend = Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmdFrontend -PassThru

@{
    iniciadoEm    = (Get-Date).ToString("o")
    portaBackend  = $PortaBackend
    portaFrontend = $PortaFrontend
    janelaBackend = $procBackend.Id
    janelaFrontend = $procFrontend.Id
} | ConvertTo-Json | Set-Content -Path $ArquivoEstado -Encoding utf8

Write-Host ""
Escrever-Passo "Aguardando os servicos responderem (limite: ${SegundosLimite}s)..."

$backendOk = Esperar-Servico "http://localhost:$PortaBackend/health" "backend" $SegundosLimite
if ($backendOk) {
    Escrever-Ok "Backend respondendo em http://localhost:$PortaBackend"
} else {
    Escrever-Erro "O backend nao respondeu em ${SegundosLimite}s."
    Write-Host "  Veja a janela do backend para a mensagem de erro." -ForegroundColor Yellow
    Write-Host "  Causa comum: dependencias faltando. Rode:" -ForegroundColor Yellow
    Write-Host "      pip install -r backend\requirements-dev.txt"
}

$frontendOk = Esperar-Servico "http://localhost:$PortaFrontend" "frontend" $SegundosLimite
if ($frontendOk) {
    Escrever-Ok "Frontend respondendo em http://localhost:$PortaFrontend"
} else {
    Escrever-Erro "O frontend nao respondeu em ${SegundosLimite}s."
    Write-Host "  Veja a janela do frontend para a mensagem de erro." -ForegroundColor Yellow
}

Write-Host ""
if ($backendOk -and $frontendOk) {
    if (-not $SemNavegador) {
        Escrever-Passo "Abrindo o navegador..."
        Start-Process "http://localhost:$PortaFrontend"
    }
    Write-Host "Tudo pronto." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Interface : http://localhost:$PortaFrontend"
    Write-Host "  API       : http://localhost:$PortaBackend"
    Write-Host "  API docs  : http://localhost:$PortaBackend/docs"
    Write-Host ""
    Write-Host "  Os arquivos sao processados neste computador. O sistema funciona" -ForegroundColor DarkGray
    Write-Host "  enquanto estas janelas estiverem abertas." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Para encerrar:  .\parar_conciliador.ps1" -ForegroundColor DarkGray
} else {
    Write-Host "Os servicos nao subiram por completo." -ForegroundColor Red
    Write-Host "  Encerre o que ficou de pe com:  .\parar_conciliador.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host ""
