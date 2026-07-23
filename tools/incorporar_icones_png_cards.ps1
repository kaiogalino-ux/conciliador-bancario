param(
    [string]$Entrada = "resultado\Modelo_principal_cards_status_icones.xlsx",
    [string]$Saida = "resultado\Modelo_principal_icones_visiveis.xlsx"
)

$ErrorActionPreference = "Stop"
$raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$entradaCompleta = [System.IO.Path]::GetFullPath((Join-Path $raiz $Entrada))
$saidaCompleta = [System.IO.Path]::GetFullPath((Join-Path $raiz $Saida))
$pastaIcones = Join-Path $raiz "resultado\icon_assets"
[System.IO.Directory]::CreateDirectory($pastaIcones) | Out-Null

Add-Type -AssemblyName System.Drawing

function New-CardIconPng {
    param([string]$Path, [string]$Text, [int]$ExcelColor)

    $r = $ExcelColor -band 255
    $g = ($ExcelColor -shr 8) -band 255
    $b = ($ExcelColor -shr 16) -band 255

    $bitmap = New-Object System.Drawing.Bitmap 96, 96
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, $r, $g, $b))
    $graphics.FillEllipse($brush, 2, 2, 92, 92)

    $fontSize = if ($Text.Length -gt 2) { 22 } elseif ($Text.Length -gt 1) { 28 } else { 40 }
    $font = New-Object System.Drawing.Font "Arial", $fontSize, ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
    $textBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
    $format = New-Object System.Drawing.StringFormat
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $graphics.DrawString($Text, $font, $textBrush, (New-Object System.Drawing.RectangleF 0, 0, 96, 96), $format)

    $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    $format.Dispose()
    $textBrush.Dispose()
    $font.Dispose()
    $brush.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
}

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
        @{ Card = "Card_Conciliado"; Texto = "OK" },
        @{ Card = "Card_Revisao"; Texto = "!" },
        @{ Card = "Card_SomenteBanco"; Texto = "X" }
    )

    foreach ($info in $icones) {
        $card = $resumo.Shapes.Item($info.Card)
        $card.TextFrame2.MarginLeft = 43
        $card.TextFrame2.MarginRight = 7
        $accent = $card.Line.ForeColor.RGB
        $arquivoIcone = Join-Path $pastaIcones "$($info.Card).png"
        New-CardIconPng $arquivoIcone $info.Texto $accent

        $size = 26
        $left = $card.Left + 9
        $top = $card.Top + (($card.Height - $size) / 2)
        $picture = $resumo.Shapes.AddPicture($arquivoIcone, 0, -1, $left, $top, $size, $size)
        $picture.Name = "CardIconPNG_$($info.Card)"
        $picture.Placement = 3
        $picture.LockAspectRatio = -1
        $picture.ZOrder(0)
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
