param(
    [string]$Entrada = "resultado\Resultado_quadro_analise_legivel.xlsx",
    [string]$Saida = "resultado\Resultado_quadro_analise_igual_imagem.xlsx"
)

$ErrorActionPreference = "Stop"
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Entrada"))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Saida"))

function Get-RgbValue([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

function Add-TableShape {
    param(
        $Sheet, [string]$Name, [double]$Left, [double]$Top,
        [double]$Width, [double]$Height, [string]$Text,
        [int]$FillColor, [int]$LineColor, [int]$FontColor,
        [double]$FontSize, [bool]$Bold, [int]$Alignment
    )

    $shape = $Sheet.Shapes.AddShape(1, $Left, $Top, $Width, $Height)
    $shape.Name = $Name
    $shape.Placement = 3
    $shape.Fill.Visible = -1
    $shape.Fill.Solid()
    $shape.Fill.ForeColor.RGB = $FillColor
    $shape.Line.Visible = -1
    $shape.Line.ForeColor.RGB = $LineColor
    $shape.Line.Weight = 0.65
    $shape.Shadow.Visible = 0

    $shape.TextFrame2.TextRange.Text = $Text
    $shape.TextFrame2.MarginLeft = 3
    $shape.TextFrame2.MarginRight = 3
    $shape.TextFrame2.MarginTop = 2
    $shape.TextFrame2.MarginBottom = 2
    $shape.TextFrame2.VerticalAnchor = 3
    $shape.TextFrame2.WordWrap = -1
    $shape.TextFrame2.TextRange.Font.Name = "Arial"
    $shape.TextFrame2.TextRange.Font.Size = $FontSize
    $shape.TextFrame2.TextRange.Font.Bold = $(if ($Bold) { -1 } else { 0 })
    $shape.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = $FontColor
    $shape.TextFrame2.TextRange.ParagraphFormat.Alignment = $Alignment
    return $shape
}

$excel = $null
$workbook = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false

    $workbook = $excel.Workbooks.Open($entradaCompleta)
    $sheet = $workbook.Worksheets.Item("Resultado")

    $inicios = @(1, 2, 4, 8, 10, 12, 14)
    $titulos = @()
    foreach ($coluna in $inicios) {
        $titulos += [string]$sheet.Cells.Item(11, $coluna).Text
    }
    $dados = @()
    foreach ($linha in 12..21) {
        $registro = @()
        foreach ($coluna in $inicios) {
            $registro += [string]$sheet.Cells.Item($linha, $coluna).Text
        }
        $dados += ,$registro
    }
    $tituloSecao = [string]$sheet.Range("A9").Text
    $subtituloSecao = [string]$sheet.Range("A10").Text

    foreach ($shape in @($sheet.Shapes)) {
        if ($shape.Name -like "QuadroAnalise_*") {
            $shape.Delete()
        }
    }

    $sheet.Range("A9:AA21").UnMerge()
    $sheet.Range("A9:AA21").Clear()

    # Reserva vertical para o quadro sem usar as células para dimensioná-lo.
    $sheet.Rows.Item(9).RowHeight = 22
    $sheet.Rows.Item(10).RowHeight = 17
    $sheet.Rows.Item(11).RowHeight = 23
    foreach ($linha in 12..21) {
        $sheet.Rows.Item($linha).RowHeight = 28
    }
    $sheet.Rows.Item(15).RowHeight = 36
    $sheet.Rows.Item(16).RowHeight = 36
    $sheet.Rows.Item(17).RowHeight = 36
    $sheet.Rows.Item(22).RowHeight = 10

    $azul = Get-RgbValue 18 55 107
    $azulClaro = Get-RgbValue 220 232 243
    $cinzaLinha = Get-RgbValue 185 197 207
    $branco = Get-RgbValue 255 255 255
    $laranja = Get-RgbValue 252 228 214
    $laranjaTexto = Get-RgbValue 156 61 0
    $vermelho = Get-RgbValue 244 204 204
    $vermelhoTexto = Get-RgbValue 156 0 6
    $cinzaTexto = Get-RgbValue 100 100 100

    $left = $sheet.Columns.Item(1).Left + 2
    $top = $sheet.Rows.Item(9).Top
    $larguras = @(60, 88, 205, 82, 82, 94, 220)

    # Título e subtítulo flutuantes.
    $titulo = Add-TableShape $sheet "QuadroAnalise_Titulo" $left $top 831 20 `
        $tituloSecao $branco $branco $azul 13 $true 1
    $titulo.TextFrame2.MarginLeft = 0

    $subtitulo = Add-TableShape $sheet "QuadroAnalise_Subtitulo" $left ($top + 20) 831 17 `
        $subtituloSecao $branco $branco $cinzaTexto 8.5 $false 1
    $subtitulo.TextFrame2.TextRange.Font.Italic = -1
    $subtitulo.TextFrame2.MarginLeft = 0

    $headerTop = $top + 39
    $x = $left
    for ($coluna = 0; $coluna -lt 7; $coluna++) {
        Add-TableShape $sheet "QuadroAnalise_Header_$coluna" $x $headerTop `
            $larguras[$coluna] 22 $titulos[$coluna] $azulClaro $cinzaLinha $azul 9 $true 2 | Out-Null
        $x += $larguras[$coluna]
    }

    $y = $headerTop + 22
    for ($linha = 0; $linha -lt $dados.Count; $linha++) {
        $altura = if ($linha -in @(3, 4, 5)) { 34 } else { 26 }
        $x = $left

        for ($coluna = 0; $coluna -lt 7; $coluna++) {
            $fundo = $branco
            $corTexto = 0
            $negrito = $false
            $alinhamento = 1

            if ($coluna -in @(0, 5)) {
                $alinhamento = 2
            }
            elseif ($coluna -in @(3, 4)) {
                $alinhamento = 3
            }

            if ($coluna -eq 5) {
                $negrito = $true
                if ($dados[$linha][$coluna] -like "*Revis*") {
                    $fundo = $laranja
                    $corTexto = $laranjaTexto
                }
                else {
                    $fundo = $vermelho
                    $corTexto = $vermelhoTexto
                }
            }

            Add-TableShape $sheet "QuadroAnalise_L$($linha)_C$coluna" $x $y `
                $larguras[$coluna] $altura $dados[$linha][$coluna] `
                $fundo $cinzaLinha $corTexto 9 $negrito $alinhamento | Out-Null
            $x += $larguras[$coluna]
        }
        $y += $altura
    }

    $sheet.Activate()
    $excel.ActiveWindow.DisplayGridlines = $false
    $excel.ActiveWindow.Zoom = 80
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
