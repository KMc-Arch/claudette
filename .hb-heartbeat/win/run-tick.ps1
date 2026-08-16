# Heartbeat tick wrapper (Windows side). Holds a SYSTEM_REQUIRED power request for the life of the
# tick so Modern Standby cannot suspend the host mid-item (a bare wsl.exe action does not prevent sleep),
# then runs the WSL tick in the foreground and exits with its code.
param(
    [string]$Distro = "claude-context",
    [string]$User   = "KMc",
    [string]$Apex   = "/mnt/claudette",
    [string]$Cmd    = "tick"
)
$sig = @'
[DllImport("kernel32.dll", SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
$k = Add-Type -MemberDefinition $sig -Name "HbPower" -Namespace "Hb" -PassThru
$ES_CONTINUOUS = 0x80000000; $ES_SYSTEM_REQUIRED = 0x00000001
[void]$k::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
try {
    & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u $User -- python3 "$Apex/.hb-heartbeat/hb.py" $Cmd.Split(" ")
    $rc = $LASTEXITCODE
} finally {
    [void]$k::SetThreadExecutionState($ES_CONTINUOUS)
}
exit $rc
