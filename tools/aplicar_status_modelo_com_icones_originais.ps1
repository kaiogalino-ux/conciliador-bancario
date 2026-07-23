param(
    [string]$Entrada = "resultado\Modelo_principal_conciliacao.xlsx",
    [string]$Saida = "resultado\Modelo_principal_conciliacao_status.xlsx"
)

$ErrorActionPreference = "Stop"
$raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $raiz $Entrada))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $raiz $Saida))

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
    $resumo = $workbook.Worksheets.Item("Resumo")

    $amareloFundo = Get-RgbValue 255 242 204
    $amarelo = Get-RgbValue 191 144 0
    $amareloTexto = Get-RgbValue 127 96 0
    $vermelhoFundo = Get-RgbValue 244 204 204
    $vermelho = Get-RgbValue 192 0 0
    $vermelhoTexto = Get-RgbValue 156 0 6
    $azulTexto = Get-RgbValue 18 55 107

    # Mantém o card e o ícone originais; altera apenas a paleta para amarelo.
    $cardRevisao = $resumo.Shapes.Item("Card_Revisao")
    $cardRevisao.Fill.ForeColor.RGB = $amareloFundo
    $cardRevisao.Line.ForeColor.RGB = $amarelo
    $cardRevisao.TextFrame2.TextRange.Paragraphs(1).Font.Fill.ForeColor.RGB = $amareloTexto
    $cardRevisao.TextFrame2.TextRange.Paragraphs(2).Font.Fill.ForeColor.RGB = $azulTexto

    # Remove apenas uma eventual versão anterior do quinto card.
    foreach ($shape in @($resumo.Shapes)) {
        if (($shape.Name -eq "Card_SomenteBanco") -or ($shape.Name -like "Icon_SomenteBanco*")) {
            $shape.Delete()
        }
    }

    $somenteBanco = 0
    foreach ($linha in 12..21) {
        $status = [string]$resumo.Cells.Item($linha, 6).Text
        if ($status -like "*Somente*banco*") {
            $somenteBanco++
        }
    }

    $total = 0
    foreach ($shapeName in @("Card_Conciliado", "Card_Revisao")) {
        $texto = [string]$resumo.Shapes.Item($shapeName).TextFrame2.TextRange.Text
        if ($texto -match "(\d+)\s*[\(\r\n]") {
            $total += [int]$Matches[1]
        }
    }
    $total += $somenteBanco
    $percentual = if ($total -gt 0) { (100 * $somenteBanco / $total) } else { 0 }
    $valorSomenteBanco = "{0}  ({1:N1}%)" -f $somenteBanco, $percentual

    # Duplica o card de revisão para preservar tipografia, cantos e proporções.
    $duplicado = $cardRevisao.Duplicate()
    $cardBanco = $duplicado
    $cardBanco.Name = "Card_SomenteBanco"
    $cardBanco.Left = $cardRevisao.Left + $cardRevisao.Width + 9
    $cardBanco.Top = $cardRevisao.Top
    $cardBanco.Width = $cardRevisao.Width
    $cardBanco.Height = $cardRevisao.Height
    $cardBanco.Fill.ForeColor.RGB = $vermelhoFundo
    $cardBanco.Line.ForeColor.RGB = $vermelho
    $cardBanco.TextFrame2.TextRange.Text = "SOMENTE NO BANCO`r$valorSomenteBanco"
    $cardBanco.TextFrame2.MarginLeft = 61
    $cardBanco.TextFrame2.MarginRight = 8
    $cardBanco.TextFrame2.TextRange.Font.Name = "Arial"
    $cardBanco.TextFrame2.TextRange.Paragraphs(1).Font.Size = 8
    $cardBanco.TextFrame2.TextRange.Paragraphs(1).Font.Bold = -1
    $cardBanco.TextFrame2.TextRange.Paragraphs(1).Font.Fill.ForeColor.RGB = $vermelhoTexto
    $cardBanco.TextFrame2.TextRange.Paragraphs(2).Font.Size = 15
    $cardBanco.TextFrame2.TextRange.Paragraphs(2).Font.Bold = -1
    $cardBanco.TextFrame2.TextRange.Paragraphs(2).Font.Fill.ForeColor.RGB = $azulTexto

    # Ícone vetorial vermelho: círculo com X, no mesmo porte dos ícones originais.
    $iconLeft = $cardBanco.Left + 15
    $iconTop = $cardBanco.Top + 13
    $iconSize = 46
    $circulo = $resumo.Shapes.AddShape(9, $iconLeft, $iconTop, $iconSize, $iconSize)
    $circulo.Name = "Icon_SomenteBanco_Circulo"
    $circulo.Placement = 3
    $circulo.Fill.Visible = 0
    $circulo.Line.Visible = -1
    $circulo.Line.ForeColor.RGB = $vermelho
    $circulo.Line.Weight = 1.25
    $circulo.Shadow.Visible = 0

    $linha1 = $resumo.Shapes.AddLine($iconLeft + 13, $iconTop + 13, $iconLeft + 33, $iconTop + 33)
    $linha1.Name = "Icon_SomenteBanco_X1"
    $linha1.Placement = 3
    $linha1.Line.ForeColor.RGB = $vermelho
    $linha1.Line.Weight = 1.5

    $linha2 = $resumo.Shapes.AddLine($iconLeft + 33, $iconTop + 13, $iconLeft + 13, $iconTop + 33)
    $linha2.Name = "Icon_SomenteBanco_X2"
    $linha2.Placement = 3
    $linha2.Line.ForeColor.RGB = $vermelho
    $linha2.Line.Weight = 1.5

    $circulo.ZOrder(0)
    $linha1.ZOrder(0)
    $linha2.ZOrder(0)

    # Mesmas cores na tabela de análise.
    foreach ($linha in 12..21) {
        $celula = $resumo.Cells.Item($linha, 6)
        $status = [string]$celula.Text
        $celula.Font.Bold = $true
        $celula.HorizontalAlignment = -4108

        if ($status -like "*Revis*") {
            $celula.Interior.Color = $amareloFundo
            $celula.Font.Color = $amareloTexto
        }
        elseif ($status -like "*Somente*banco*") {
            $celula.Interior.Color = $vermelhoFundo
            $celula.Font.Color = $vermelhoTexto
        }
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
