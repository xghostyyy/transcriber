# Создаёт ярлык «Транскрибатор» на рабочем столе (Windows).
# Запуск: powershell -ExecutionPolicy Bypass -File scripts/install_shortcut.ps1

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "scripts\transcriber.cmd"
$icon = Join-Path $root "assets\transcriber.ico"

if (-not (Test-Path $launcher)) {
    Write-Error "Не найден $launcher"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Транскрибатор.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Транскрибатор видео: вставь ссылку — получи текст"
if (Test-Path $icon) {
    $shortcut.IconLocation = $icon
}
$shortcut.Save()

Write-Host "Готово: $shortcutPath"
