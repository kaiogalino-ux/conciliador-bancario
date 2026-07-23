param(
    [string]$Entrada = "resultado\Resultado_cards_e_tabelas_independentes.xlsx",
    [string]$Saida = "resultado\Modelo_principal_conciliacao.xlsx"
)

$ErrorActionPreference = "Stop"
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

function Get-RgbValue([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

function Add-SectionIcon {
    param(
        $Sheet, [string]$Name, $AnchorCell, [string]$Symbol,
        [int]$Background, [int]$Foreground
    )

    $left = $AnchorCell.Left + 1
    $top = $AnchorCell.Top + 2
    $size = 15
    $shape = $Sheet.Shapes.AddShape(9, $left, $top, $size, $size)
    $shape.Name = $Name
    $shape.Placement = 3
    $shape.Fill.Visible = -1
    $shape.Fill.Solid()
    $shape.Fill.ForeColor.RGB = $Background
    $shape.Line.Visible = 0
    $shape.Shadow.Visible = 0
    $shape.TextFrame2.TextRange.Text = $Symbol
    $shape.TextFrame2.MarginLeft = 0
    $shape.TextFrame2.MarginRight = 0
    $shape.TextFrame2.MarginTop = 0
    $shape.TextFrame2.MarginBottom = 0
    $shape.TextFrame2.VerticalAnchor = 3
    $shape.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
    $shape.TextFrame2.TextRange.Font.Name = "Arial"
    $shape.TextFrame2.TextRange.Font.Size = 9
    $shape.TextFrame2.TextRange.Font.Bold = -1
    $shape.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = $Foreground
}

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $resumo = $workbook.Worksheets.Item("Resumo")
    $base = $workbook.Worksheets.Item("Base Detalhada")

    foreach ($aba in @($resumo, $base)) {
        foreach ($shape in @($aba.Shapes)) {
            if ($shape.Name -like "SectionIcon_*") {
                $shape.Delete()
            }
        }
    }

    # Remove as legendas pequenas sob os títulos dos quadros.
    $resumo.Range("A10:G10").ClearContents()
    $resumo.Rows.Item(10).RowHeight = 7

    # Ícones de identificação dos dois quadros.
    $azul = Get-RgbValue 18 55 107
    $azulClaro = Get-RgbValue 220 232 243
    $laranja = Get-RgbValue 198 89 17
    $laranjaClaro = Get-RgbValue 252 228 214
    $branco = Get-RgbValue 255 255 255

    Add-SectionIcon $resumo "SectionIcon_Pendencias" $resumo.Range("A9") "!" $laranjaClaro $laranja
    Add-SectionIcon $base "SectionIcon_Base" $base.Range("A1") "≡" $azul $branco

    $resumo.Range("A9").IndentLevel = 3
    $resumo.Range("A9").Font.Size = 12
    $resumo.Rows.Item(9).RowHeight = 21
    $base.Range("A1").IndentLevel = 3
    $base.Range("A1").Font.Size = 12
    $base.Rows.Item(1).RowHeight = 23

    # Mantém o arquivo limpo ao abrir.
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
