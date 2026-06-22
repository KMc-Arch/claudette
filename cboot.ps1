<#
.SYNOPSIS
  Thin wrapper around cboot.py — "run cboot here" (PowerShell; 5.1 and 7+).
.DESCRIPTION
  Resolves the claudette apex, then dispatches by where you are:
    - at the apex root -> full boot           ( python cboot.py @args )
    - inside a child   -> refresh that child  ( python cboot.py --project <root> @args )

  Apex resolution — bedrock is the CLAUDE.md that declares apex-root: true:
    1. If $env:CLAUDETTE_HOME is set, it WINS. It must be a valid apex (a dir
       whose CLAUDE.md declares apex-root: true, containing cboot.py) or we fail
       loudly — never a silent fall-back to walk-up. Use it when claudette and
       your projects live in different trees (decohered).
    2. Otherwise walk up from CWD to the dir whose CLAUDE.md declares
       apex-root: true. Hard error if none is found.
    In both cases the apex must contain cboot.py, else hard error.

  "child" = nearest ancestor (at or above CWD) whose CLAUDE.md declares
  root: true / apex-root: true — i.e. the context root ^.
  An explicit --project / -p anywhere in the args is passed through unchanged.
#>

$ErrorActionPreference = 'Stop'

function Test-ApexRoot([string]$dir) {
  $cm = Join-Path $dir 'CLAUDE.md'
  return (Test-Path $cm) -and (Select-String -Path $cm -Pattern '^apex-root:\s*true' -Quiet)
}

# Walk up from CWD to the apex (dir whose CLAUDE.md declares apex-root: true).
function Find-ApexByMarker {
  $d = (Get-Location).Path
  while ($d) {
    if (Test-ApexRoot $d) { return $d }
    $parent = Split-Path $d -Parent
    if (-not $parent -or $parent -eq $d) { break }
    $d = $parent
  }
  return $null
}

# Nearest root:true / apex-root:true ancestor at or above CWD (the context root ^).
function Find-Root([string]$apex) {
  $d = (Get-Location).Path
  while ($true) {
    $cm = Join-Path $d 'CLAUDE.md'
    if ((Test-Path $cm) -and (Select-String -Path $cm -Pattern '^(root|apex-root):\s*true' -Quiet)) {
      return $d
    }
    if ($d -eq $apex) { break }
    $parent = Split-Path $d -Parent
    if (-not $parent -or $parent -eq $d) { break }
    $d = $parent
  }
  return $null
}

if ($env:CLAUDETTE_HOME) {
  # Explicit apex wins — validate it, never silently fall back to walk-up.
  if (-not (Test-Path $env:CLAUDETTE_HOME -PathType Container)) {
    Write-Error "cboot: CLAUDETTE_HOME is not a directory: $env:CLAUDETTE_HOME"; exit 1
  }
  $apex = (Resolve-Path $env:CLAUDETTE_HOME).Path
  if (-not (Test-ApexRoot $apex)) {
    Write-Error "cboot: CLAUDETTE_HOME is not an apex (no CLAUDE.md with 'apex-root: true'): $apex"; exit 1
  }
} else {
  $apex = Find-ApexByMarker
  if (-not $apex) {
    Write-Error "cboot: apex not found (no CLAUDE.md with 'apex-root: true' above CWD). Set CLAUDETTE_HOME."; exit 1
  }
}

if (-not (Test-Path (Join-Path $apex 'cboot.py'))) {
  Write-Error "cboot: apex at $apex has no cboot.py (malformed install)."; exit 1
}

$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $pyCmd) { Write-Error "cboot: no python interpreter on PATH (tried python, python3)."; exit 1 }
$py = $pyCmd.Source

$cboot = Join-Path $apex 'cboot.py'

# An explicit --project always wins — pass everything straight through.
foreach ($a in $args) {
  if ($a -eq '--project' -or $a -like '--project=*' -or $a -eq '-p') {
    & $py $cboot @args
    exit $LASTEXITCODE
  }
}

$root = Find-Root $apex
if (-not $root) { $root = (Get-Location).Path }

if ($root -eq $apex) {
  & $py $cboot @args                        # at apex: full boot
} else {
  & $py $cboot --project $root @args         # in child: refresh this project
}
exit $LASTEXITCODE
