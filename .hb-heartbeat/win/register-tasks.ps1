# Heartbeat — Windows Task Scheduler registration (run in Windows PowerShell as the logged-on user).
# Registers three tasks that call into WSL:
#   hb-window-open   daily at <open>   -> hb.py window open
#   hb-window-close  daily at <close>  -> hb.py window close
#   hb-tick          every <tick> min  -> hb.py tick   (foreground; the tick IS the runner while an item runs)
# Re-running is idempotent (tasks are replaced). Remove with:  -Unregister
# Monitor with:  /checkWinTasks hb-
param(
    [string]$Distro = "claude-context",
    [string]$User   = "KMc",
    [string]$Apex   = "/mnt/claudette",
    [string]$Open   = "00:30",
    [string]$Close  = "06:30",
    [int]$TickMin   = 5,
    [int]$ItemCapMin = 90,
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$names = @("hb-window-open", "hb-window-close", "hb-tick")
if ($Unregister) {
    foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Output "unregistered: $($names -join ', ')"; exit 0
}
$wsl = "$env:SystemRoot\System32\wsl.exe"
$py  = "$Apex/.hb-heartbeat/hb.py"
function Act([string]$cmd) {
    # -u runs as the WSL user; a non-login shell — hb.py/runner.py fix PATH themselves (config.extra_path)
    New-ScheduledTaskAction -Execute $wsl -Argument "-d $Distro -u $User -- python3 $py $cmd"
}
$settingsTick = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes ($ItemCapMin + 15))
$settingsWin  = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# S4U = run whether the user is logged on or not, no stored password. If registration is refused
# (needs "Log on as a batch job"), re-run with -LogonType Interactive (task then needs a logged-on session).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

$tOpen  = New-ScheduledTaskTrigger -Daily -At $Open
$tClose = New-ScheduledTaskTrigger -Daily -At $Close
# tick: repeat every N minutes, indefinitely (window gating happens inside hb.py via the GO flag)
$tTick  = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $TickMin)

Register-ScheduledTask -TaskName "hb-window-open"  -Action (Act "window open")  -Trigger $tOpen  -Settings $settingsWin  -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName "hb-window-close" -Action (Act "window close") -Trigger $tClose -Settings $settingsWin  -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName "hb-tick"         -Action (Act "tick")         -Trigger $tTick  -Settings $settingsTick -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName "hb-*" | Format-Table TaskName, State -AutoSize
