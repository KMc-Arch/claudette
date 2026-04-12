param(
    [switch]$Kick,
    [Parameter(ValueFromRemainingArguments)][string[]]$Patterns
)

$tasks = @()
foreach ($p in $Patterns) {
    $tasks += Get-ScheduledTask | Where-Object { $_.TaskName -like "*$p*" }
}
$tasks = $tasks | Sort-Object TaskName -Unique

$results = foreach ($t in $tasks) {
    $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath
    $ago  = if ($info.LastRunTime) { ((Get-Date) - $info.LastRunTime).TotalHours } else { 999 }
    $stale = $ago -gt 20
    $kicked = $false

    if ($Kick -and $stale) {
        Start-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath
        $kicked = $true
    }

    [PSCustomObject]@{
        Task     = $t.TaskName
        State    = $t.State
        LastRun  = if ($info.LastRunTime) { $info.LastRunTime.ToString("yyyy-MM-dd HH:mm") } else { "Never" }
        HoursAgo = [math]::Round($ago, 1)
        Stale    = if ($stale) { "YES" } else { "no" }
        Kicked   = if ($kicked) { "KICKED" } else { "" }
    }
}
$results | Format-Table -AutoSize
