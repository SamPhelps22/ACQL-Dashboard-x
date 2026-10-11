# ---------------------------------------------------------------------
#  ACQL - scheduled background runs (acql/headless.py), no window needed.
#
#    ACQL Daily          every day at 3:00 AM: ESPN results, replay
#                        timelines, predictions, website - all of it.
#    ACQL Game-day poll  Thu, Sun and Mon, every 10 minutes from 9 AM to
#                        midnight. Only does anything when a game is under
#                        way or has just finished; otherwise it's gone in a
#                        second.
#
#  Run it again after moving the folder. To take both away:
#      powershell -ExecutionPolicy Bypass -File schedule.ps1 -Remove
#  What each run did goes in data\acql-log.txt, lines starting "headless:".
# ---------------------------------------------------------------------
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$names = "ACQL Daily", "ACQL Game-day poll"

foreach ($name in $names) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}
if ($Remove) { Write-Host "  Both ACQL scheduled tasks removed."; exit 0 }

# pythonw: the venv's Python without a console window popping up at 3am.
$python = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
    Write-Host "  No .venv yet - double-click 'ACQL Dashboard.bat' once to set it up, then run this again."
    exit 1
}

# A missed run (PC off or asleep at 3am) happens as soon as it's back.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

$daily = New-ScheduledTaskAction -Execute $python -Argument "-m acql.headless --daily" -WorkingDirectory $root
# The PC sleeps overnight: wake it for the 3am run (and keep it awake until done).
$wake = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew -WakeToRun
Register-ScheduledTask -TaskName "ACQL Daily" -Action $daily -Settings $wake `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 3:00AM) `
    -Description "ACQL Dashboard: results, replays and the pool website, every night." | Out-Null

# A weekly trigger can't take a repetition itself; borrow one from a one-off trigger.
$poll = New-ScheduledTaskAction -Execute $python -Argument "-m acql.headless --poll" -WorkingDirectory $root
$gameDays = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday, Sunday, Monday -At 9:00AM
$gameDays.Repetition = (New-ScheduledTaskTrigger -Once -At 9:00AM `
    -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 15)).Repetition
Register-ScheduledTask -TaskName "ACQL Game-day poll" -Action $poll -Settings $settings `
    -Trigger $gameDays `
    -Description "ACQL Dashboard: live results and the pool website during games." | Out-Null

Write-Host "  Scheduled:"
Write-Host "    ACQL Daily          every day at 3:00 AM"
Write-Host "    ACQL Game-day poll  Thu/Sun/Mon, every 10 min, 9 AM - midnight"
Write-Host "  Runs while you're signed in to Windows. Log: data\acql-log.txt"
