<#
Full build: PyInstaller (Python + all dependencies + ffmpeg into one bundle) -> Inno Setup
(installer with the "Next/Finish" wizard, desktop shortcut, user data kept in a separate
per-user folder). Result: installer\Output\RyatuvalnychokSetup.exe

Build machine requirements: the project's .venv (requirements.txt + requirements-build.txt),
and Inno Setup 6 (ISCC.exe) - if missing: winget install JRSoftware.InnoSetup

Note: this file is plain ASCII on purpose. Windows PowerShell 5.1 reads .ps1 files without a
BOM using the system codepage, not UTF-8 - non-ASCII text here breaks parsing on machines
where that codepage isn't UTF-8 (see the git history of this file for what that looks like).
#>
param(
    [switch]$SkipInstaller
)

# Deliberately NOT using $ErrorActionPreference = 'Stop': in Windows PowerShell 5.1 that
# promotes ordinary stderr output from native exes (pip notices, etc.) into terminating
# errors. Instead every native call below is checked explicitly via $LASTEXITCODE.
$root = Split-Path -Parent $PSScriptRoot
$installerDir = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python venv not found at $python - create .venv and install requirements.txt first (see project README)."
}

Write-Output "== Checking build dependencies (PyInstaller) =="
& $python -m pip install -q -r (Join-Path $installerDir "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit code $LASTEXITCODE)" }

Write-Output "== Reading version from app/version.py =="
$version = & $python -c "from app.version import __version__; print(__version__)"
$version = $version.Trim()
Write-Output "Version: $version"

Write-Output "== Cleaning build/ and dist/ =="
Remove-Item -Recurse -Force (Join-Path $root "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $root "dist") -ErrorAction SilentlyContinue

Write-Output "== PyInstaller: building Ryatuvalnychok =="
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean (Join-Path $installerDir "ryatuvalnychok.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit code $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$exePath = Join-Path $root "dist\Ryatuvalnychok\Ryatuvalnychok.exe"
if (-not (Test-Path $exePath)) {
    throw "PyInstaller build did not produce $exePath - see output above."
}
Write-Output "PyInstaller bundle ready: $exePath"

if ($SkipInstaller) {
    Write-Output "== -SkipInstaller: skipping Inno Setup build =="
    exit 0
}

Write-Output "== Looking for ISCC.exe (Inno Setup 6) =="
$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    throw "ISCC.exe not found. Install Inno Setup 6: winget install JRSoftware.InnoSetup"
}
Write-Output "Using: $iscc"

Write-Output "== Inno Setup: building installer =="
& $iscc "/DMyAppVersion=$version" (Join-Path $installerDir "ryatuvalnychok.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit code $LASTEXITCODE)" }

$setupExe = Join-Path $installerDir "Output\RyatuvalnychokSetup.exe"
Write-Output ""
Write-Output "== Done =="
Write-Output "Installer: $setupExe"
