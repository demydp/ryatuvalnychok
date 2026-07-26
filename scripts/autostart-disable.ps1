<#
Убирает ярлык дашборда из папки «Автозагрузка» Windows.
#>
$startupDir = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startupDir "Рятувальничок.lnk"

if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Output "Автозагрузка отключена."
} else {
    Write-Output "Автозагрузка не была включена."
}
