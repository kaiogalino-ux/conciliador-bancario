param(
    [string]$Entrada = "resultado\Modelo_principal_cards_status.xlsx",
    [string]$Saida = "resultado\Modelo_principal_cards_status_icones.xlsx"
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
    $resumo = $workbook.Worksheets.Item("Resumo")

    foreach ($shape in @($resumo.Shapes)) {
        if ($shape.Name -like "CardIcon_*") {
            $shape.Delete()
        }
    }

    $icones = @(
        @{ Card = "Card_Gestao"; Texto = "ERP" },
        @{ Card = "Card_Banco"; Texto = "B" },
        @{ Card = "Card_Conciliado"; Texto = [string][char]0x2713 },
        @{ Card = "Card_Revisao"; Texto = "!" },
        @{ Card = "Card_SomenteBanco"; Texto = [string][char]0x00D7 }
    )

    foreach ($info in $icones) {
        $card = $resumo.Shapes.Item($info.Card)
        $card.TextFrame2.MarginLeft = 42
        $card.TextFrame2.MarginRight = 8

        $size = 25
        $left = $card.Left + 10
        $top = $card.Top + (($card.Height - $size) / 2)
        $accent = $card.Line.ForeColor.RGB

        $icon = $resumo.Shapes.AddShape(9, $left, $top, $size, $size)
        $icon.Name = "CardIcon_$($info.Card)"
        $icon.Placement = 3
        $icon.Fill.Visible = -1
        $icon.Fill.Solid()
        $icon.Fill.ForeColor.RGB = $accent
        $icon.Line.Visible = 0
        $icon.Shadow.Visible = 0
        $icon.TextFrame2.TextRange.Text = $info.Texto
        $icon.TextFrame2.MarginLeft = 0
        $icon.TextFrame2.MarginRight = 0
        $icon.TextFrame2.MarginTop = 0
        $icon.TextFrame2.MarginBottom = 0
        $icon.TextFrame2.VerticalAnchor = 3
        $icon.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
        $icon.TextFrame2.TextRange.Font.Name = "Arial"
        $icon.TextFrame2.TextRange.Font.Size = $(if ($info.Texto -eq "ERP") { 7 } else { 12 })
        $icon.TextFrame2.TextRange.Font.Bold = -1
        $icon.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = 16777215
        $icon.ZOrder(0)
    }

    $resumo.Activate()
    $resumo.Range("A9").Select()
    $excel.ActiveWindow.DisplayGridlines = $false
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
