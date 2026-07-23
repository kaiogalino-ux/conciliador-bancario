param(
    [string]$Entrada = "resultado\Modelo_principal_conciliacao.xlsx",
    [string]$Saida = "resultado\Modelo_principal_cards_status.xlsx"
)

$ErrorActionPreference = "Stop"
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

function Get-RgbValue([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

function Add-StatusCard {
    param(
        $Sheet, [string]$Name, [double]$Left, [double]$Top,
        [double]$Width, [double]$Height, [string]$Text,
        [int]$Background, [int]$Accent, [string]$Icon
    )

    $card = $Sheet.Shapes.AddShape(5, $Left, $Top, $Width, $Height)
    $card.Name = $Name
    $card.Placement = 3
    $card.Fill.Visible = -1
    $card.Fill.Solid()
    $card.Fill.ForeColor.RGB = $Background
    $card.Line.Visible = -1
    $card.Line.ForeColor.RGB = $Accent
    $card.Line.Weight = 1.4
    $card.Shadow.Visible = 0
    $card.TextFrame2.TextRange.Text = $Text
    $card.TextFrame2.MarginLeft = 10
    $card.TextFrame2.MarginRight = 34
    $card.TextFrame2.MarginTop = 7
    $card.TextFrame2.MarginBottom = 5
    $card.TextFrame2.VerticalAnchor = 1
    $card.TextFrame2.WordWrap = -1

    $range = $card.TextFrame2.TextRange
    $range.Font.Name = "Arial"
    $range.Font.Size = 8
    $range.Font.Fill.ForeColor.RGB = Get-RgbValue 38 55 70

    $quantidadeParagrafos = $range.Paragraphs().Count
    $range.Paragraphs(1).Font.Size = 7.5
    $range.Paragraphs(1).Font.Bold = -1
    $range.Paragraphs(1).Font.Fill.ForeColor.RGB = $Accent
    if ($quantidadeParagrafos -ge 2) {
        $range.Paragraphs(2).Font.Size = 13
        $range.Paragraphs(2).Font.Bold = -1
        $range.Paragraphs(2).Font.Fill.ForeColor.RGB = Get-RgbValue 18 55 107
    }
    if ($quantidadeParagrafos -ge 3) {
        $range.Paragraphs(3).Font.Size = 7.5
        $range.Paragraphs(3).Font.Italic = -1
        $range.Paragraphs(3).Font.Fill.ForeColor.RGB = Get-RgbValue 100 110 118
    }

    $iconShape = $Sheet.Shapes.AddShape(9, $Left + $Width - 27, $Top + 8, 19, 19)
    $iconShape.Name = "CardIcon_$Name"
    $iconShape.Placement = 3
    $iconShape.Fill.Visible = -1
    $iconShape.Fill.Solid()
    $iconShape.Fill.ForeColor.RGB = $Accent
    $iconShape.Line.Visible = 0
    $iconShape.Shadow.Visible = 0
    $iconShape.TextFrame2.TextRange.Text = $Icon
    $iconShape.TextFrame2.MarginLeft = 0
    $iconShape.TextFrame2.MarginRight = 0
    $iconShape.TextFrame2.MarginTop = 0
    $iconShape.TextFrame2.MarginBottom = 0
    $iconShape.TextFrame2.VerticalAnchor = 3
    $iconShape.TextFrame2.TextRange.ParagraphFormat.Alignment = 2
    $iconShape.TextFrame2.TextRange.Font.Name = "Arial"
    $iconShape.TextFrame2.TextRange.Font.Size = 9
    $iconShape.TextFrame2.TextRange.Font.Bold = -1
    $iconShape.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = Get-RgbValue 255 255 255
}

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $resumo = $workbook.Worksheets.Item("Resumo")

    $textos = @{}
    foreach ($nome in @("Card_Gestao", "Card_Banco", "Card_Conciliado", "Card_Revisao")) {
        $textoOriginal = [string]$resumo.Shapes.Item($nome).TextFrame2.TextRange.Text
        $partes = @($textoOriginal -split "[\r\n\v]+")
        while ($partes.Count -lt 3) {
            $partes += ""
        }
        $textos[$nome] = "$($partes[0])`r$($partes[1])`r$($partes[2])"
    }

    $somenteBanco = 0
    foreach ($linha in 12..21) {
        $status = [string]$resumo.Cells.Item($linha, 6).Text
        if ($status -like "*Somente*banco*") {
            $somenteBanco++
        }
    }
    $sufixo = if ($somenteBanco -eq 1) { "registro" } else { "registros" }
    $textos["Card_SomenteBanco"] = "SOMENTE NO BANCO`r$somenteBanco $sufixo`rSem correspondencia no ERP"

    foreach ($shape in @($resumo.Shapes)) {
        if (($shape.Name -like "Card_*") -or ($shape.Name -like "CardIcon_*")) {
            $shape.Delete()
        }
    }

    $azulFundo = Get-RgbValue 234 243 248
    $azul = Get-RgbValue 30 90 133
    $cianoFundo = Get-RgbValue 231 244 250
    $ciano = Get-RgbValue 34 139 180
    $verdeFundo = Get-RgbValue 226 240 217
    $verde = Get-RgbValue 82 135 62
    $amareloFundo = Get-RgbValue 255 242 204
    $amarelo = Get-RgbValue 191 144 0
    $vermelhoFundo = Get-RgbValue 244 204 204
    $vermelho = Get-RgbValue 192 0 0

    $left = $resumo.Columns.Item(1).Left + 2
    $top = $resumo.Rows.Item(4).Top + 2
    $width = 164
    $height = 72
    $gap = 8

    $cards = @(
        @{ Nome = "Card_Gestao"; Texto = $textos["Card_Gestao"]; Fundo = $azulFundo; Cor = $azul; Icone = '$' },
        @{ Nome = "Card_Banco"; Texto = $textos["Card_Banco"]; Fundo = $cianoFundo; Cor = $ciano; Icone = 'B' },
        @{ Nome = "Card_Conciliado"; Texto = $textos["Card_Conciliado"]; Fundo = $verdeFundo; Cor = $verde; Icone = [string][char]0x2713 },
        @{ Nome = "Card_Revisao"; Texto = $textos["Card_Revisao"]; Fundo = $amareloFundo; Cor = $amarelo; Icone = '!' },
        @{ Nome = "Card_SomenteBanco"; Texto = $textos["Card_SomenteBanco"]; Fundo = $vermelhoFundo; Cor = $vermelho; Icone = [string][char]0x00D7 }
    )

    for ($i = 0; $i -lt $cards.Count; $i++) {
        $info = $cards[$i]
        Add-StatusCard $resumo $info.Nome ($left + ($i * ($width + $gap))) $top `
            $width $height $info.Texto $info.Fundo $info.Cor $info.Icone
    }

    # Cores equivalentes na tabela de análise.
    foreach ($linha in 12..21) {
        $statusCell = $resumo.Cells.Item($linha, 6)
        $status = [string]$statusCell.Text
        $statusCell.Font.Bold = $true
        $statusCell.HorizontalAlignment = -4108

        if ($status -like "*Revis*") {
            $statusCell.Interior.Color = $amareloFundo
            $statusCell.Font.Color = Get-RgbValue 127 96 0
        }
        elseif ($status -like "*Somente*banco*") {
            $statusCell.Interior.Color = $vermelhoFundo
            $statusCell.Font.Color = Get-RgbValue 156 0 6
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
