param(
    [string]$Entrada = "resultado\Resultado_cards_compactos.xlsx",
    [string]$Saida = "resultado\Resultado_cards_independentes.xlsx"
)

$ErrorActionPreference = "Stop"

function Get-RgbValue([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $sheet = $workbook.Worksheets.Item("Resultado")

    $totalGestao = $sheet.Range("B5").Value2
    $totalBanco = $sheet.Range("F5").Value2
    $conciliado = [string]$sheet.Range("J5").Value2
    $revisao = [string]$sheet.Range("N5").Value2

    foreach ($shape in @($sheet.Shapes)) {
        if ($shape.Name -like "Card_*") {
            $shape.Delete()
        }
    }

    $sheet.Range("A4:P7").UnMerge()
    $sheet.Range("A4:P7").ClearContents()
    $sheet.Range("A4:P7").Interior.Pattern = -4142
    $sheet.Range("A4:P7").Borders.LineStyle = -4142

    $sheet.Rows("4:8").RowHeight = 15
    $top = $sheet.Rows.Item(4).Top + 2
    $left = $sheet.Columns.Item(1).Left + 2
    $width = 205
    $height = 72
    $gap = 10

    $cards = @(
        @{
            Nome = "Card_Gestao"; Titulo = "TOTAL NA GESTÃO"; Valor = ("R$ {0:N2}" -f $totalGestao)
            Nota = "Total registrado no ERP"; Fundo = (Get-RgbValue 234 243 248); Borda = (Get-RgbValue 30 90 133)
        },
        @{
            Nome = "Card_Banco"; Titulo = "TOTAL NO BANCO"; Valor = ("R$ {0:N2}" -f $totalBanco)
            Nota = "Total identificado no extrato"; Fundo = (Get-RgbValue 231 244 250); Borda = (Get-RgbValue 34 139 180)
        },
        @{
            Nome = "Card_Conciliado"; Titulo = "CONCILIADO"; Valor = $conciliado
            Nota = "Registros conciliados"; Fundo = (Get-RgbValue 226 240 217); Borda = (Get-RgbValue 82 135 62)
        },
        @{
            Nome = "Card_Revisao"; Titulo = "REVISÃO MANUAL"; Valor = $revisao
            Nota = "Registros para conferência"; Fundo = (Get-RgbValue 252 228 214); Borda = (Get-RgbValue 198 89 17)
        }
    )

    for ($i = 0; $i -lt $cards.Count; $i++) {
        $cardInfo = $cards[$i]
        $cardLeft = $left + ($i * ($width + $gap))
        $shape = $sheet.Shapes.AddShape(5, $cardLeft, $top, $width, $height)
        $shape.Name = $cardInfo.Nome
        $shape.Placement = 3
        $shape.LockAspectRatio = 0
        $shape.Fill.Visible = -1
        $shape.Fill.Solid()
        $shape.Fill.ForeColor.RGB = $cardInfo.Fundo
        $shape.Line.Visible = -1
        $shape.Line.ForeColor.RGB = $cardInfo.Borda
        $shape.Line.Weight = 1.5
        $shape.Shadow.Visible = 0

        $texto = "$($cardInfo.Titulo)`r$($cardInfo.Valor)`r$($cardInfo.Nota)"
        $shape.TextFrame2.TextRange.Text = $texto
        $shape.TextFrame2.MarginLeft = 12
        $shape.TextFrame2.MarginRight = 10
        $shape.TextFrame2.MarginTop = 7
        $shape.TextFrame2.MarginBottom = 5
        $shape.TextFrame2.VerticalAnchor = 1
        $shape.TextFrame2.WordWrap = -1

        $range = $shape.TextFrame2.TextRange
        $range.Font.Name = "Arial"
        $range.Font.Size = 9
        $range.Font.Fill.ForeColor.RGB = (Get-RgbValue 38 55 70)

        $titulo = $range.Paragraphs(1)
        $titulo.Font.Size = 8
        $titulo.Font.Bold = -1
        $titulo.Font.Fill.ForeColor.RGB = $cardInfo.Borda

        $valor = $range.Paragraphs(2)
        $valor.Font.Size = 15
        $valor.Font.Bold = -1
        $valor.Font.Fill.ForeColor.RGB = (Get-RgbValue 18 55 107)

        $nota = $range.Paragraphs(3)
        $nota.Font.Size = 8
        $nota.Font.Italic = -1
        $nota.Font.Fill.ForeColor.RGB = (Get-RgbValue 100 110 118)
    }

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
