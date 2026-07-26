<#
Останавливает Reels Dashboard. Матчинг по командной строке ненадёжен: venv-python.exe
на некоторых системах — это редиректор-заглушка, которая запускает глобальный python.exe
как дочерний процесс, и командная строка ребёнка может не содержать полного пути к run.py.
Поэтому находим процесс, который реально слушает порт 5000 (то же самое, что "сервер
запущен" означает и для start.bat), и останавливаем его — вместе с родителем-заглушкой,
если она есть.
#>
$conns = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue

if (-not $conns) {
    Write-Output "Дашборд не запущен."
} else {
    $ownerPids = $conns.OwningProcess | Sort-Object -Unique
    foreach ($ownerPid in $ownerPids) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -ErrorAction SilentlyContinue
        if ($proc -and $proc.ParentProcessId) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
            if ($parent -and ($parent.Name -eq 'python.exe' -or $parent.Name -eq 'pythonw.exe')) {
                Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
    }
    Write-Output "Остановлено (PID: $($ownerPids -join ', '))."
}
