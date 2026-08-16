# Heartbeat — Windows Task Scheduler registration (run in Windows PowerShell as the logged-on user):
#   powershell -ExecutionPolicy Bypass -File D:\claudette\.hb-heartbeat\win\register-tasks.ps1
# Registers three tasks:
#   hb-window-open   daily at <Open>  (wakes the machine)              -> hb.py window open
#   hb-window-close  daily at <Close>                                  -> hb.py window close
#   hb-tick          every <TickMin> min, ONLY between Open and Close  -> run-tick.ps1 (keep-awake) -> hb.py tick
# The tick trigger repeats for the window duration only, so the laptop is not woken every 5 minutes all day.
# During a run, run-tick.ps1 holds a SYSTEM_REQUIRED power request so Modern Standby does not suspend mid-item.
# Re-running is idempotent (tasks are replaced). Remove with:  -Unregister.  Monitor with:  /checkWinTasks hb-
# NOTE: keep -ItemCapMin equal to config.json item_cap_min (ExecutionTimeLimit = ItemCapMin + 15); re-register if you change it.
param(
    [string]$Distro = "claude-context",
    [string]$User   = "KMc",
    [string]$Apex   = "/mnt/claudette",
    [string]$WinApex = "D:\claudette",
    [string]$Open   = "00:30",
    [string]$Close  = "06:30",
    [int]$TickMin   = 5,
    [int]$ItemCapMin = 90,
    [ValidateSet("S4U", "Interactive")][string]$LogonType = "S4U",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$names = @("hb-window-open", "hb-window-close", "hb-tick")
if ($Unregister) {
    foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Output "unregistered: $($names -join ', ')"; exit 0
}
$wsl = "$env:SystemRoot\System32\wsl.exe"
$ps  = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$py  = "$Apex/.hb-heartbeat/hb.py"
$tickWrapper = Join-Path $WinApex ".hb-heartbeat\win\run-tick.ps1"
if (-not (Test-Path $tickWrapper)) { throw "run-tick.ps1 not found at $tickWrapper — pass -WinApex" }

$openT  = [DateTime]::ParseExact($Open,  "HH:mm", $null)
$closeT = [DateTime]::ParseExact($Close, "HH:mm", $null)
$windowLen = if ($closeT -gt $openT) { $closeT - $openT } else { ($closeT.AddDays(1)) - $openT }

$actOpen  = New-ScheduledTaskAction -Execute $wsl -Argument "-d $Distro -u $User -- python3 $py window open"
$actClose = New-ScheduledTaskAction -Execute $wsl -Argument "-d $Distro -u $User -- python3 $py window close"
$actTick  = New-ScheduledTaskAction -Execute $ps  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$tickWrapper`" -Distro $Distro -User $User -Apex $Apex -Cmd tick"

# tick: WakeToRun is safe here because the repetition is bounded to the window (no all-day wakeups)
$settingsTick = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes ($ItemCapMin + 15))
$settingsOpen = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$settingsClose = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# S4U = run whether the user is logged on or not, no stored password (needs "Log on as a batch job").
# If registration is refused, re-run with -LogonType Interactive (task then needs a logged-on session).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType $LogonType -RunLevel Limited

$tOpen  = New-ScheduledTaskTrigger -Daily -At $Open
$tClose = New-ScheduledTaskTrigger -Daily -At $Close
# tick: daily at Open+2min (after hb-window-open has issued GO), repeating every TickMin for the window's length only
$tickStart = $openT.AddMinutes(2).ToString("HH:mm")
$tTick  = New-ScheduledTaskTrigger -Daily -At $tickStart
$tTick.Repetition = (New-ScheduledTaskTrigger -Once -At $tickStart -RepetitionInterval (New-TimeSpan -Minutes $TickMin) -RepetitionDuration ($windowLen - (New-TimeSpan -Minutes 2))).Repetition

Register-ScheduledTask -TaskName "hb-window-open"  -Action $actOpen  -Trigger $tOpen  -Settings $settingsOpen  -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName "hb-window-close" -Action $actClose -Trigger $tClose -Settings $settingsClose -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName "hb-tick"         -Action $actTick  -Trigger $tTick  -Settings $settingsTick  -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName "hb-*" | Format-Table TaskName, State -AutoSize
Write-Output "Pre-flight (proves the S4U/session-0 path): Start-ScheduledTask hb-tick ; then check $WinApex\.hb-heartbeat\state\last-tick"
