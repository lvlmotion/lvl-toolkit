# Bootstrap a self-contained Python env for the lvl-toolkit + the app-sensor-desktop
# recorder's "Plot last session" / vicon bridge buttons.
#
# What it does, cwd-independent (safe to double-click or run from anywhere):
#   1. finds a base Python >= 3.9 (py launcher preferred, else python on PATH)
#   2. creates a .venv inside this repo (gitignored)
#   3. installs this toolkit editable into it (pulls numpy/pandas/matplotlib)
#   4. points the recorder at that venv by setting the LVL_BRIDGE_PYTHON user env var
#
# The recorder resolves its interpreter from LVL_BRIDGE_PYTHON (see
# PlotSessionProcess.kt / ViconBridgeProcess.kt), so one venv serves both the
# grapher and the mocap bridge. Re-run any time to repair the env.
#
# Usage:  powershell -ExecutionPolicy Bypass -File bootstrap.ps1

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$venv = Join-Path $repo ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"

Write-Host "lvl-toolkit bootstrap" -ForegroundColor Cyan
Write-Host "  repo: $repo"

# --- 1. find a base interpreter >= 3.9 ---------------------------------------
function Test-Py($exe, $argsPrefix) {
    try {
        $v = & $exe @argsPrefix -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) {
            $p = $v.Split('.'); $maj=[int]$p[0]; $min=[int]$p[1]
            if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 9)) { return $v.Trim() }
        }
    } catch {}
    return $null
}

$base = $null; $baseArgs = @()
# py launcher first (handles multiple installs cleanly), then plain python
if ((Get-Command py -ErrorAction SilentlyContinue) -and (Test-Py "py" @("-3"))) {
    $base = "py"; $baseArgs = @("-3")
} elseif ((Get-Command python -ErrorAction SilentlyContinue) -and (Test-Py "python" @())) {
    $base = "python"; $baseArgs = @()
}
if (-not $base) {
    Write-Host "ERROR: no Python >= 3.9 found on this machine." -ForegroundColor Red
    Write-Host "Install Python 3.9+ from python.org (tick 'Add to PATH'), then re-run." -ForegroundColor Red
    exit 1
}
$baseVer = Test-Py $base $baseArgs
Write-Host "  base python: $base $($baseArgs -join ' ')  (v$baseVer)"

# --- 2. create the venv ------------------------------------------------------
if (-not (Test-Path $venvPy)) {
    Write-Host "  creating venv at .venv ..."
    & $base @baseArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: venv creation failed." -ForegroundColor Red; exit 1 }
} else {
    Write-Host "  reusing existing .venv"
}

# --- 3. install the toolkit + deps into the venv -----------------------------
Write-Host "  installing lvl-toolkit (+ numpy/pandas/matplotlib) ..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -e $repo
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pip install failed." -ForegroundColor Red; exit 1 }

# --- 4. point the recorder at this venv --------------------------------------
& $venvPy -c "import lvl_toolkit,sys;print('  verified: lvl_toolkit at',lvl_toolkit.__file__)"
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: lvl_toolkit still not importable." -ForegroundColor Red; exit 1 }

setx LVL_BRIDGE_PYTHON "$venvPy" | Out-Null
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  LVL_BRIDGE_PYTHON = $venvPy  (set for your user account)"
Write-Host "  RESTART the recorder app so it picks up the new env var, then Plot last session." -ForegroundColor Yellow
