param(
    [string]$Entrada = "resultado\Resultado_cards_independentes.xlsx",
    [string]$Saida = "resultado\Resultado_cards_e_tabelas_independentes.xlsx"
)

$ErrorActionPreference = "Stop"
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $resumo = $workbook.Worksheets.Item("Resultado")
    $resumo.Name = "Resumo"

    foreach ($aba in @($workbook.Worksheets)) {
        if ($aba.Name -eq "Base Detalhada") {
            $aba.Delete()
        }
    }

    $base = $workbook.Worksheets.Add()
    $base.Name = "Base Detalhada"
    $resumo.Move($workbook.Worksheets.Item(1))

    # Copia a seção completa para outra aba, mantendo valores e formatação.
    $origem = $resumo.Range("A23:AA187")
    $destino = $base.Range("A1:AA165")
    $origem.Copy($destino)

    # Remove a base detalhada da primeira aba. Cards e pendências permanecem.
    $resumo.Range("A23:AA187").Clear()
    $resumo.Rows("23:187").RowHeight = 15

    # A primeira aba passa a usar larguras próprias para a tabela de pendências.
    $largurasResumo = @(12, 18, 42, 16, 16, 19, 48)
    for ($i = 1; $i -le $largurasResumo.Count; $i++) {
        $resumo.Columns.Item($i).ColumnWidth = $largurasResumo[$i - 1]
    }
    $resumo.Columns("H:AA").ColumnWidth = 3
    $resumo.Range("A11:G21").WrapText = $true
    $resumo.Range("A11:G21").VerticalAlignment = -4108
    $resumo.Rows("12:21").AutoFit()
    foreach ($linha in 12..21) {
        if ($resumo.Rows.Item($linha).RowHeight -lt 22) {
            $resumo.Rows.Item($linha).RowHeight = 22
        }
    }
    $resumo.Activate()
    $excel.ActiveWindow.DisplayGridlines = $false
    $excel.ActiveWindow.Zoom = 90
    $excel.ActiveWindow.FreezePanes = $false
    $resumo.PageSetup.PrintArea = '$A$1:$G$21'
    $resumo.PageSetup.Orientation = 2
    $resumo.PageSetup.Zoom = $false
    $resumo.PageSetup.FitToPagesWide = 1
    $resumo.PageSetup.FitToPagesTall = 1

    # Na base detalhada, cada coluna recebe largura conforme o seu conteúdo.
    $largurasBase = @(
        15, 22, 20, 18, 15, 16, 16, 32, 38, 42, 19, 22, 34, 34,
        36, 15, 16, 18, 19, 38, 22, 18, 18, 14, 38, 20, 18
    )
    for ($i = 1; $i -le $largurasBase.Count; $i++) {
        $base.Columns.Item($i).ColumnWidth = $largurasBase[$i - 1]
    }
    $base.Range("A2:AA163").WrapText = $true
    $base.Range("A2:AA163").VerticalAlignment = -4108
    $base.Rows.Item(1).RowHeight = 26
    $base.Rows.Item(2).RowHeight = 38
    foreach ($linha in 3..163) {
        $base.Rows.Item($linha).RowHeight = 30
    }
    $base.Range("A2:AA163").AutoFilter()
    $base.Activate()
    $excel.ActiveWindow.DisplayGridlines = $false
    $excel.ActiveWindow.Zoom = 80
    $excel.ActiveWindow.FreezePanes = $false
    $base.Range("A3").Select()
    $excel.ActiveWindow.FreezePanes = $true
    $base.PageSetup.PrintArea = '$A$1:$AA$165'
    $base.PageSetup.PrintTitleRows = '$1:$2'
    $base.PageSetup.Orientation = 2
    $base.PageSetup.Zoom = $false
    $base.PageSetup.FitToPagesWide = 1
    $base.PageSetup.FitToPagesTall = $false

    $resumo.Activate()
    $resumo.Range("A9").Select()
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
