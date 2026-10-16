# Генерирует assets/transcriber.ico — иконку приложения для ярлыка на рабочем столе.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts/make_icon.ps1

Add-Type -AssemblyName System.Drawing

function New-RoundedRectPath([int]$x, [int]$y, [int]$w, [int]$h, [int]$r) {
    $d = $r * 2
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x, $y, $d, $d, 180, 90)
    $path.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $path.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $path.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

$size = 256
$bitmap = New-Object System.Drawing.Bitmap($size, $size)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

# Тёмный скруглённый фон в тон интерфейсу (#0F172A)
$background = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 15, 23, 42))
$graphics.FillPath($background, (New-RoundedRectPath 8 8 240 240 56))

# Циановая звуковая волна (#22D3EE), центральный столбик светлее (#67E8F9)
$accent = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 34, 211, 238))
$bright = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 103, 232, 249))
$heights = @(72, 120, 168, 120, 72)
$barWidth = 20
$gap = 17
$x = 44

for ($i = 0; $i -lt $heights.Count; $i++) {
    $h = $heights[$i]
    $y = [int](($size - $h) / 2)
    $brush = if ($i -eq 2) { $bright } else { $accent }
    $graphics.FillPath($brush, (New-RoundedRectPath $x $y $barWidth $h ($barWidth / 2)))
    $x += $barWidth + $gap
}

# Сохраняем как PNG и упаковываем в ICO-контейнер (256x256, как поддерживает Windows)
$stream = New-Object System.IO.MemoryStream
$bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $stream.ToArray()

$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root "assets\transcriber.ico"
New-Item -ItemType Directory -Path (Split-Path -Parent $output) -Force | Out-Null

$file = [System.IO.File]::Create($output)
$writer = New-Object System.IO.BinaryWriter($file)
$writer.Write([uint16]0)            # reserved
$writer.Write([uint16]1)            # type: icon
$writer.Write([uint16]1)            # одна картинка
$writer.Write([byte]0)              # ширина 0 = 256
$writer.Write([byte]0)              # высота 0 = 256
$writer.Write([byte]0)              # палитра
$writer.Write([byte]0)              # reserved
$writer.Write([uint16]1)            # planes
$writer.Write([uint16]32)           # бит на пиксель
$writer.Write([uint32]$png.Length)  # размер картинки
$writer.Write([uint32]22)           # смещение картинки
$writer.Write($png)
$writer.Close()
$file.Close()

$graphics.Dispose()
$bitmap.Dispose()
Write-Host "Готово: $output ($((Get-Item $output).Length) байт)"
