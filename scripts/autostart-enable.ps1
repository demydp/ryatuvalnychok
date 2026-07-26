<#
Кладёт ярлык в папку «Автозагрузка» Windows (shell:startup) — при входе в систему
дашборд поднимается сам, тихо (pythonw, без консоли), без открытия браузера.
#>
$root = Split-Path -Parent $PSScriptRoot
$startupDir = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupDir "Рятувальничок.lnk"
$iconPath = Join-Path $root "dashboard.ico"

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($lnkPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\start.ps1`" -NoBrowser"
$shortcut.WorkingDirectory = $root
if (Test-Path $iconPath) { $shortcut.IconLocation = $iconPath }
$shortcut.Description = "Автозапуск Рятувальничка при входе в Windows"
$shortcut.WindowStyle = 7
$shortcut.Save()

Write-Output "Автозагрузка включена: $lnkPath"
