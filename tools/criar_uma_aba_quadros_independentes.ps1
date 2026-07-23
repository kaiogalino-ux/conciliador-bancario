param(
    [string]$Entrada = "resultado\Resultado_cards_independentes.xlsx",
    [string]$Saida = "resultado\Resultado_tabelas_dados_tamanhos_diferentes.xlsx"
)

$ErrorActionPreference = "Stop"
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

function Get-RgbValue([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $sheet = $workbook.Worksheets.Item("Resultado")

    # Guarda os dados do quadro de pendências antes de reconstruí-lo.
    $titulos = @()
    foreach ($coluna in 1..7) {
        $titulos += $sheet.Cells.Item(11, $coluna).Value2
    }
    $dados = @()
    foreach ($linha in 12..21) {
        $registro = @()
        foreach ($coluna in 1..7) {
            $registro += $sheet.Cells.Item($linha, $coluna).Value2
        }
        $dados += ,$registro
    }

    $tituloSecao = $sheet.Range("A9").Value2
    $subtituloSecao = $sheet.Range("A10").Value2

    $sheet.Range("A9:AA21").UnMerge()
    $sheet.Range("A9:AA21").Clear()

    # Cada campo do quadro superior ocupa seu próprio grupo de colunas.
    # Isso permite larguras visuais diferentes das 27 colunas da base detalhada.
    $grupos = @(
        @{ Inicio = 1; Fim = 1 }, # Data
        @{ Inicio = 2; Fim = 2 }, # Origem
        @{ Inicio = 3; Fim = 4 }, # Favorecido / descrição
        @{ Inicio = 5; Fim = 5 }, # Valor Gestão
        @{ Inicio = 6; Fim = 6 }, # Valor banco
        @{ Inicio = 7; Fim = 7 }, # Status
        @{ Inicio = 8; Fim = 9 }  # Motivo
    )

    $sheet.Range("A9:I9").Merge()
    $sheet.Range("A10:I10").Merge()
    $sheet.Range("A9").Value2 = $tituloSecao
    $sheet.Range("A10").Value2 = $subtituloSecao

    $azul = Get-RgbValue 18 55 107
    $azulClaro = Get-RgbValue 220 232 243
    $cinzaLinha = Get-RgbValue 201 208 214
    $branco = Get-RgbValue 255 255 255
    $laranja = Get-RgbValue 252 228 214
    $laranjaTexto = Get-RgbValue 156 61 0
    $vermelho = Get-RgbValue 244 204 204
    $vermelhoTexto = Get-RgbValue 156 0 6

    $sheet.Range("A9").Font.Name = "Arial"
    $sheet.Range("A9").Font.Size = 13
    $sheet.Range("A9").Font.Bold = $true
    $sheet.Range("A9").Font.Color = $azul
    $sheet.Range("A10").Font.Name = "Arial"
    $sheet.Range("A10").Font.Size = 9
    $sheet.Range("A10").Font.Italic = $true
    $sheet.Range("A10").Font.Color = Get-RgbValue 107 107 107
    $sheet.Rows.Item(9).RowHeight = 22
    $sheet.Rows.Item(10).RowHeight = 18

    for ($indice = 0; $indice -lt $grupos.Count; $indice++) {
        $grupo = $grupos[$indice]
        $cabecalho = $sheet.Range(
            $sheet.Cells.Item(11, $grupo.Inicio),
            $sheet.Cells.Item(11, $grupo.Fim)
        )
        $cabecalho.Merge()
        $cabecalho.Value2 = $titulos[$indice]
        $cabecalho.Interior.Color = $azulClaro
        $cabecalho.Font.Name = "Arial"
        $cabecalho.Font.Size = 9
        $cabecalho.Font.Bold = $true
        $cabecalho.Font.Color = $azul
        $cabecalho.HorizontalAlignment = -4108
        $cabecalho.VerticalAlignment = -4108
        $cabecalho.WrapText = $true
        $cabecalho.Borders.LineStyle = 1
        $cabecalho.Borders.Color = $cinzaLinha
        $cabecalho.Borders.Weight = 2
    }
    $sheet.Rows.Item(11).RowHeight = 25

    for ($indiceLinha = 0; $indiceLinha -lt $dados.Count; $indiceLinha++) {
        $linhaPlanilha = 12 + $indiceLinha
        $registro = $dados[$indiceLinha]

        for ($indice = 0; $indice -lt $grupos.Count; $indice++) {
            $grupo = $grupos[$indice]
            $celula = $sheet.Range(
                $sheet.Cells.Item($linhaPlanilha, $grupo.Inicio),
                $sheet.Cells.Item($linhaPlanilha, $grupo.Fim)
            )
            $celula.Merge()
            $valorExibido = $registro[$indice]
            if (($indice -eq 0) -and ($valorExibido -is [double])) {
                $valorExibido = [DateTime]::FromOADate($valorExibido).ToString("dd/MM/yyyy")
            }
            elseif (($indice -in @(3, 4)) -and ($valorExibido -is [double])) {
                $valorExibido = "R$ " + $valorExibido.ToString("N2")
            }
            elseif ($null -ne $valorExibido) {
                $valorExibido = [string]$valorExibido
            }
            if ($indice -eq 0) {
                $celula.NumberFormat = "@"
            }
            $sheet.Cells.Item($linhaPlanilha, $grupo.Inicio).Value2 = $valorExibido
            $celula.Interior.Color = $branco
            $celula.Font.Name = "Arial"
            $celula.Font.Size = 9
            $celula.Font.Color = 0
            $celula.VerticalAlignment = -4108
            $celula.WrapText = $true
            $celula.Borders.LineStyle = 1
            $celula.Borders.Color = $cinzaLinha
            $celula.Borders.Weight = 2

            if ($indice -in @(0, 5)) {
                $celula.HorizontalAlignment = -4108
            }
            elseif ($indice -in @(3, 4)) {
                $celula.HorizontalAlignment = -4152
            }
            else {
                $celula.HorizontalAlignment = -4131
            }
        }

        $status = [string]$registro[5]
        $statusRange = $sheet.Range(
            $sheet.Cells.Item($linhaPlanilha, 7),
            $sheet.Cells.Item($linhaPlanilha, 7)
        )
        if ($status -like "*Revis*") {
            $statusRange.Interior.Color = $laranja
            $statusRange.Font.Color = $laranjaTexto
            $statusRange.Font.Bold = $true
        }
        elseif (-not [string]::IsNullOrWhiteSpace($status)) {
            $statusRange.Interior.Color = $vermelho
            $statusRange.Font.Color = $vermelhoTexto
            $statusRange.Font.Bold = $true
        }

        $descricao = [string]$registro[2]
        $motivo = [string]$registro[6]
        if (($descricao.Length -gt 55) -or ($motivo.Length -gt 75)) {
            $sheet.Rows.Item($linhaPlanilha).RowHeight = 42
        }
        else {
            $sheet.Rows.Item($linhaPlanilha).RowHeight = 30
        }
    }

    # Larguras orientadas pela base detalhada; o quadro superior não depende
    # delas visualmente porque seus sete campos são mesclados em grupos.
    $largurasBase = @(
        12, 16, 20, 20, 15, 15, 18, 22, 22, 36, 17, 20, 28, 28,
        30, 13, 14, 16, 17, 32, 19, 16, 16, 12, 32, 18, 17
    )
    for ($i = 1; $i -le $largurasBase.Count; $i++) {
        $sheet.Columns.Item($i).ColumnWidth = $largurasBase[$i - 1]
    }

    # Mesma qualidade de leitura no quadro detalhado.
    $sheet.Range("A24:AA185").WrapText = $true
    $sheet.Range("A24:AA185").VerticalAlignment = -4108
    $sheet.Rows.Item(24).RowHeight = 40
    foreach ($linha in 25..185) {
        $sheet.Rows.Item($linha).RowHeight = 30
    }

    $sheet.Activate()
    $excel.ActiveWindow.DisplayGridlines = $false
    $excel.ActiveWindow.Zoom = 80
    $excel.ActiveWindow.FreezePanes = $false
    $sheet.Range("A25").Select()
    $excel.ActiveWindow.FreezePanes = $true
    $sheet.PageSetup.PrintArea = '$A$1:$AA$187'
    $sheet.PageSetup.PrintTitleRows = '$24:$24'
    $sheet.PageSetup.Orientation = 2
    $sheet.PageSetup.Zoom = $false
    $sheet.PageSetup.FitToPagesWide = 1
    $sheet.PageSetup.FitToPagesTall = $false

    $sheet.Range("A9").Select()
    $workbook.SaveAs($saidaCompleta, 51)
    $workbook.Close($true)
    $workbook = $null

    Write-Output "CRIADO=$saidaCompleta"
}
finally {
    if ($null -ne $workbook) {
        $workbook.Close($false)
    }
    if ($null -ne $excel) {
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
