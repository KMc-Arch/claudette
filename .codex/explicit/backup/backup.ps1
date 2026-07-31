<#
    claudette backup - mirror this instance to its configured backup target.

    The target, exclusions and schedule are per-install and live in
    ^/.state/backup.json. That file is gitignored by .state/.gitignore, so it
    never travels with the codex; a fresh install supplies its own.

    Robocopy's exit codes are normalised here: its success codes (<8) become 0
    so Task Scheduler does not report every successful run as a failure. Only
    genuine failures (>=8) propagate.

    ASCII only. Windows PowerShell 5.1 reads .ps1 as ANSI unless the file has a
    UTF-8 BOM, so any non-ASCII character here becomes a parse error.
#>
param(
    [switch]$DryRun,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$Root       = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$ConfigPath = Join-Path $Root '.state\backup.json'

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Error "No backup config at $ConfigPath - see .codex/explicit/backup/start.md"
    exit 16
}

$cfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($cfg.target)) {
    Write-Error "backup.json declares no 'target'"
    exit 16
}

$Target  = [Environment]::ExpandEnvironmentVariables($cfg.target)
$LogPath = [Environment]::ExpandEnvironmentVariables(
    $(if ($cfg.log) { $cfg.log } else { '%LOCALAPPDATA%\claudette\backup.log' }))
$HistPath = [Environment]::ExpandEnvironmentVariables(
    $(if ($cfg.history) { $cfg.history } else { '%LOCALAPPDATA%\claudette\backup-history.log' }))

# The target's parent must already exist. Robocopy creates the leaf, but a typo
# in a synced path would otherwise silently mirror into a folder OneDrive does
# not watch.
$TargetParent = Split-Path -Parent $Target
if (-not (Test-Path -LiteralPath $TargetParent)) {
    Write-Error "Backup target's parent does not exist: $TargetParent"
    exit 16
}

foreach ($dir in @((Split-Path -Parent $LogPath), (Split-Path -Parent $HistPath))) {
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# /XJ skips every reparse point. That is deliberate: the venv lib64 links are
# unresolvable from Windows and generate error spam, and AggregatorM\Delivery
# points at a live SharePoint library that must not be pulled into the backup.
$rcArgs = @(
    $Root
    $Target
    '/MIR'          # mirror: destination becomes an exact copy
    '/XJ'           # never follow junctions or symlinks
    '/DCOPY:DAT'    # preserve directory timestamps
    '/R:1'          # one retry
    '/W:1'          # one second between retries
    '/NP'           # no per-file progress (this is what makes logs enormous)
    '/NDL'          # no directory list
    "/LOG:$LogPath"
)
if (-not $Quiet) { $rcArgs += '/TEE' }
if ($DryRun)     { $rcArgs += '/L' }

# /XF and /XD each consume every following token until the next switch, so the
# two exclusion lists go last and each is introduced by its own switch.
#
# exclude_files is a security control, not an optimisation. The backup target is
# a cloud-synced folder, so anything mirrored there is uploaded, retained in
# version history, and recoverable long after the source is cleaned. Credential
# files are gitignored and therefore invisible to `scrub full`, which scans only
# tracked files -- they must be excluded here by name instead.
$excludeFiles = @($cfg.exclude_files | Where-Object { $_ })
if ($excludeFiles.Count) { $rcArgs += '/XF'; $rcArgs += $excludeFiles }

# An exclude_dirs entry containing a slash is treated as root-relative and
# expanded to a full path, so a specific directory can be excluded without
# also excluding every same-named directory elsewhere in the tree. A bare name
# is passed through and matches at any depth, which is what the venv and
# __pycache__ entries want.
$excludeDirs = @($cfg.exclude_dirs | Where-Object { $_ } | ForEach-Object {
    if ($_ -match '[\\/]') { Join-Path $Root ($_ -replace '/', '\') } else { $_ }
})
if ($excludeDirs.Count) { $rcArgs += '/XD'; $rcArgs += $excludeDirs }

$robocopy = Join-Path $env:SystemRoot 'System32\Robocopy.exe'
& $robocopy @rcArgs
$code = $LASTEXITCODE

$verdict = if ($code -ge 8) { 'FAIL' } elseif ($code -eq 0) { 'NOCHANGE' } else { 'OK' }
$stamp   = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$mode    = if ($DryRun) { ' (dry-run)' } else { '' }
$line    = "$stamp  $verdict  rc=$code$mode  $Root -> $Target"

Add-Content -LiteralPath $HistPath -Value $line

if (-not $Quiet) {
    Write-Host ''
    Write-Host $line
    Write-Host "Log:     $LogPath"
    Write-Host "History: $HistPath"
}

# Normalise for Task Scheduler.
if ($code -ge 8) { exit $code } else { exit 0 }
