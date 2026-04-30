[CmdletBinding()]
param(
    [string]$Name = "claudette",
    [string]$Branch = "main"
)

$ErrorActionPreference = 'Stop'

$RepoUrl = "https://github.com/KMc-Arch/claudette.git"

function Write-Section($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)      { Write-Host "[OK]   $text" -ForegroundColor Green }
function Write-Miss($text)    { Write-Host "[MISS] $text" -ForegroundColor Yellow }
function Write-Err($text)     { Write-Host "[ERR]  $text" -ForegroundColor Red }

function Test-Cmd($cmd) { $null -ne (Get-Command $cmd -ErrorAction SilentlyContinue) }

function Test-PythonVersion {
    if (-not (Test-Cmd 'py') -and -not (Test-Cmd 'python')) { return $false }
    $exe = if (Test-Cmd 'py') { 'py' } else { 'python' }
    try {
        $r = & $exe -c "import sys; print(1 if sys.version_info >= (3,10) else 0)" 2>$null
        return $r.Trim() -eq '1'
    } catch { return $false }
}

function Test-RealBash {
    if (-not (Test-Cmd 'bash')) { return $false }
    try {
        $v = & bash --version 2>$null | Select-Object -First 1
        return $v -like "*GNU bash*"
    } catch { return $false }
}

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable('Path','Machine')
    $user    = [System.Environment]::GetEnvironmentVariable('Path','User')
    $env:PATH = "$machine;$user"
}

Write-Host ""
Write-Host "Claudette installer" -ForegroundColor White
Write-Host "-------------------"

Write-Section "Preflight"

$missing = @()
if (Test-Cmd 'git')         { Write-Ok 'git' }                else { Write-Miss 'git';                $missing += 'git' }
if (Test-PythonVersion)     { Write-Ok 'python (>=3.10)' }    else { Write-Miss 'python (>=3.10)';    $missing += 'python' }
if (Test-Cmd 'node')        { Write-Ok 'node' }               else { Write-Miss 'node';               $missing += 'node' }
if (Test-Cmd 'claude')      { Write-Ok 'claude' }             else { Write-Miss 'claude';             $missing += 'claude' }
if (Test-RealBash)          { Write-Ok 'bash (GNU)' }         else { Write-Miss 'bash (GNU)';         $missing += 'bash' }

if ($missing.Count -gt 0) {
    if (-not (Test-Cmd 'winget')) {
        Write-Err "winget not found. Install missing prereqs manually:"
        foreach ($m in $missing) {
            switch ($m) {
                'git'    { Write-Host "  git    : https://git-scm.com/download/win  (also provides GNU bash)" }
                'python' { Write-Host "  python : https://www.python.org/downloads/  (3.10 or newer)" }
                'node'   { Write-Host "  node   : https://nodejs.org/" }
                'claude' { Write-Host "  claude : npm install -g @anthropic-ai/claude-code" }
                'bash'   { Write-Host "  bash   : install Git for Windows (provides GNU bash)" }
            }
        }
        exit 1
    }

    Write-Host ""
    Write-Host "Missing: $($missing -join ', ')"
    $reply = Read-Host "Install automatically via winget+npm? [Y/n]"
    if ($reply -ne '' -and $reply.ToLower() -ne 'y' -and $reply.ToLower() -ne 'yes') {
        Write-Err "Declined. Install the listed prereqs manually, then re-run."
        exit 1
    }

    $needGit    = ('git' -in $missing) -or ('bash' -in $missing)
    $needPy     = 'python' -in $missing
    $needNode   = ('node' -in $missing) -or ('claude' -in $missing -and -not (Test-Cmd 'npm'))
    $needClaude = 'claude' -in $missing

    if ($needGit) {
        Write-Section "Installing git (includes GNU bash)"
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
    }
    if ($needPy) {
        Write-Section "Installing python 3.12"
        winget install --id Python.Python.3.12 -e --source winget --accept-source-agreements --accept-package-agreements
    }
    if ($needNode) {
        Write-Section "Installing node.js"
        winget install --id OpenJS.NodeJS -e --source winget --accept-source-agreements --accept-package-agreements
    }

    Refresh-Path

    if ($needClaude) {
        if (Test-Cmd 'npm') {
            Write-Section "Installing claude-code via npm"
            & npm install -g '@anthropic-ai/claude-code'
        } else {
            Write-Err "npm not on PATH after Node install. Close this window, open a new PowerShell, and paste the one-liner again. (Installer is idempotent.)"
            exit 1
        }
    }

    Refresh-Path

    Write-Section "Re-verifying prereqs"
    $stillMissing = @()
    if (-not (Test-Cmd 'git'))     { $stillMissing += 'git' }
    if (-not (Test-PythonVersion)) { $stillMissing += 'python' }
    if (-not (Test-Cmd 'claude'))  { $stillMissing += 'claude' }
    if (-not (Test-RealBash))      { $stillMissing += 'bash' }
    if ($stillMissing.Count -gt 0) {
        Write-Err "Still missing: $($stillMissing -join ', ')"
        Write-Host "Close this window, open a NEW PowerShell, then paste the one-liner again."
        Write-Host "(The installer is idempotent. New shells pick up freshly installed PATH entries.)"
        exit 1
    }
    Write-Ok "All prereqs ready"
}

Write-Section "Acquire"

$installPath = Join-Path $PWD.Path $Name

if (Test-Path $installPath) {
    Write-Host "Existing install detected: $installPath"
    Push-Location $installPath
    try {
        & git pull
        if ($LASTEXITCODE -ne 0) {
            Write-Err "git pull failed. Resolve local changes inside $installPath manually, then re-run."
            exit 1
        }
        Write-Ok "Updated"
    } finally {
        Pop-Location
    }
} else {
    & git clone --branch $Branch $RepoUrl $installPath
    if ($LASTEXITCODE -ne 0) {
        Write-Err "git clone failed."
        exit 1
    }
    Write-Ok "Cloned to $installPath"
}

Write-Section "Install cdt shim"

$binDir    = Join-Path $installPath 'bin'
$cmdShim   = Join-Path $binDir 'cdt.cmd'
$cbootPath = Join-Path $installPath 'cboot.py'

New-Item -ItemType Directory -Path $binDir -Force | Out-Null

# Shim prefers the Python launcher (`py -3`) when present, else falls back to
# `python`. The launcher is more PATH-stable across Python upgrades on Windows.
$shimContent = @"
@echo off
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "$cbootPath" %*
) else (
    python "$cbootPath" %*
)
"@

Set-Content -Path $cmdShim -Value $shimContent -Encoding ASCII
Write-Ok "Wrote shim: $cmdShim"

$userPath = [System.Environment]::GetEnvironmentVariable('Path','User')
if (-not $userPath) { $userPath = '' }
$pathParts = $userPath.Split(';') | Where-Object { $_ -ne '' }
if ($pathParts -notcontains $binDir) {
    $newUserPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
    Write-Ok "Added $binDir to user PATH"
} else {
    Write-Ok "$binDir already on user PATH"
}

if (($env:PATH -split ';') -notcontains $binDir) {
    $env:PATH = "$env:PATH;$binDir"
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  1. If this is your first time, authenticate Claude Code:  claude"
Write-Host "  2. Then start a Claudette session:  cdt"
Write-Host ""
Write-Host "  cdt is available in this window now. New PowerShell or cmd windows"
Write-Host "  will pick it up automatically."
Write-Host ""
