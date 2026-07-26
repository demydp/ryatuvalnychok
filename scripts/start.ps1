<#
Поднимает Reels Dashboard в фоне (pythonw.exe — без чёрного окна консоли) и открывает
браузер на 127.0.0.1:5000. Если сервер уже отвечает на этом порту — новый процесс не
плодит, просто открывает вкладку (или ничего не делает при -NoBrowser, см. автозагрузку).
#>
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$runpy = Join-Path $root "run.py"
$url = "http://127.0.0.1:5000/"
$logPath = Join-Path $PSScriptRoot "start.log"

function Write-Log($message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $message" | Out-File -FilePath $logPath -Append -Encoding utf8
}

function Test-ServerUp {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect("127.0.0.1", 5000, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(500)
        if ($ok -and $client.Connected) { $client.Close(); return $true }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

if (-not (Test-Path $pythonw)) {
    Write-Log "ОШИБКА: не найден $pythonw — виртуальное окружение не создано?"
    exit 1
}

# Мьютекс на случай двойного запуска (два быстрых даблклика) — второй экземпляр
# просто дождётся порта вместо того, чтобы стартовать вторую копию сервера.
$mutex = New-Object System.Threading.Mutex($false, "Global\ReelsDashboardStartLock")
$acquiredLock = $mutex.WaitOne(0)

try {
    if (-not (Test-ServerUp)) {
        if ($acquiredLock) {
            Write-Log "Сервер не отвечает — запускаем pythonw run.py"
            Start-Process -FilePath $pythonw -ArgumentList "`"$runpy`"" -WorkingDirectory $root
        } else {
            Write-Log "Другой процесс уже запускает сервер — ждём порт"
        }

        $tries = 0
        while (-not (Test-ServerUp) -and $tries -lt 40) {
            Start-Sleep -Milliseconds 500
            $tries++
        }

        if (Test-ServerUp) {
            Write-Log "Сервер поднялся"
        } else {
            Write-Log "ОШИБКА: сервер не ответил за 20 секунд"
        }
    } else {
        Write-Log "Сервер уже был запущен"
    }
} finally {
    if ($acquiredLock) { $mutex.ReleaseMutex() }
}

if (-not $NoBrowser) {
    Start-Process $url
}
