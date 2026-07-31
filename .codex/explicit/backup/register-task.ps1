<#
    Register (or remove) the Windows scheduled task that runs backup.ps1.

    Task name, run time and logon trigger come from ^/.state/backup.json, so a
    different install can schedule differently without editing the codex.

    The task runs as the invoking user with Limited rights. It needs no
    elevation, and it must run as the user because the backup target lives in
    that user's OneDrive profile.

    ASCII only - see the note in backup.ps1.
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'

$Root       = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$ConfigPath = Join-Path $Root '.state\backup.json'

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Write-Error "No backup config at $ConfigPath - see .codex/explicit/backup/start.md"
    exit 1
}

$cfg      = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$TaskName = if ($cfg.task_name) { $cfg.task_name } else { 'claudette-backup' }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Unregistered scheduled task: $TaskName"
    exit 0
}

$ScriptPath = Join-Path $PSScriptRoot 'backup.ps1'
$PwshPath   = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$action = New-ScheduledTaskAction -Execute $PwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -Quiet"

$time     = if ($cfg.schedule.time) { $cfg.schedule.time } else { '12:30' }
$triggers = @(New-ScheduledTaskTrigger -Daily -At $time)
if ($cfg.schedule.at_logon) {
    $triggers += New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
}

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# StartWhenAvailable catches up a run missed while the machine was off.
# IgnoreNew prevents a long mirror from overlapping the next trigger.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $triggers -Principal $principal -Settings $settings `
    -Description "Mirror $Root to its configured OneDrive backup target (see .state/backup.json)" `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "  Runs   : daily at $time$(if ($cfg.schedule.at_logon) { ' + at logon' })"
Write-Host "  Action : $ScriptPath -Quiet"
Write-Host "  Check  : /checkWinTasks $TaskName"
