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
# uint32 literals: in Windows PowerShell 5.1 a bare 0x80000000 is a NEGATIVE Int32 and the P/Invoke throws (silently, in a task)
[uint32]$ES_CONTINUOUS = 2147483648; [uint32]$ES_SYSTEM_REQUIRED = 1
$prev = $k::SetThreadExecutionState([uint32]($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED))
if ($prev -eq 0) { Write-Warning "SetThreadExecutionState failed; host may sleep mid-item" }
try {
    & "$env:SystemRoot\System32\wsl.exe" -d $Distro -u $User -- python3 "$Apex/.hb-heartbeat/hb.py" $Cmd.Split(" ")
    $rc = $LASTEXITCODE
} finally {
    [void]$k::SetThreadExecutionState($ES_CONTINUOUS)
}
exit $rc
