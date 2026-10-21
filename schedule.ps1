# ---------------------------------------------------------------------
#  ACQL - scheduled background runs (acql/headless.py), no window needed.
#
#    ACQL Daily          every day at 3:00 AM: ESPN results, replay
#                        timelines, predictions, website - all of it.
#    ACQL Game-day poll  Thu, Sun and Mon, every 10 minutes from 9 AM to
#                        midnight. Only does anything when a game is under
#                        way or has just finished; otherwise it's gone in a
#                        second.
#    ACQL Deadeye email  Tue, Wed and Thu at 12:00 noon: Deadeye's card for
#                        the week ahead, on the freshest lines, emailed to
#                        the dashboard's own address - and nobody else.
#    ACQL Training       Tue, Wed and Thu at 12:30 PM: freezes the week's
#                        numbers as they stand before the deadline, and once
#                        a week teaches the challengers again and writes the
#                        answer the Model Lab shows. Changes no pick.
#    ACQL Sunday brief   Sun at 9:00 AM: the week's top calls, line moves
#                        since open and the odds budget, emailed to you -
#                        from stored lines only, so it costs no requests.
#    ACQL Operation      every day, every 2 hours from 9 AM to 9 PM: the
#      Sunday            shadow forecast job (operation_sunday/). Refreshes
#                        the week's draft on the latest stored lines and locks
#                        it within 3 hours of the Thursday deadline (or an
#                        earlier first kickoff). Uses stored lines only, so it
#                        costs no Odds API requests. Changes no pick, page or
#                        site. Log: data\operation_sunday\run.log
#
#  Run it again after moving the folder. To take them all away:
#      powershell -ExecutionPolicy Bypass -File schedule.ps1 -Remove
#  What each run did goes in data\acql-log.txt, lines starting "headless:".
# ---------------------------------------------------------------------
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$names = "ACQL Daily", "ACQL Game-day poll", "ACQL Deadeye email", "ACQL Training", "ACQL Sunday brief",
    "ACQL Operation Sunday"

foreach ($name in $names) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}
if ($Remove) { Write-Host "  The ACQL scheduled tasks are removed."; exit 0 }

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

# The card by email: woken for, like the 3am run, so a sleeping PC still sends it.
$mail = New-ScheduledTaskAction -Execute $python -Argument "-m acql.headless --email" -WorkingDirectory $root
Register-ScheduledTask -TaskName "ACQL Deadeye email" -Action $mail -Settings $wake `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday, Wednesday, Thursday -At 12:00PM) `
    -Description "ACQL Dashboard: Deadeye's card for the week ahead, emailed to you." | Out-Null

# The training ground: half an hour after the email, so it freezes the lines that fetched.
$train = New-ScheduledTaskAction -Execute $python -Argument "-m acql.training weekly" -WorkingDirectory $root
Register-ScheduledTask -TaskName "ACQL Training" -Action $train -Settings $wake `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday, Wednesday, Thursday -At 12:30PM) `
    -Description "ACQL Dashboard: the week's numbers frozen before the deadline, and the challengers' weekly test." | Out-Null

# The Sunday brief: woken for, so it is in the inbox before the early games.
$brief = New-ScheduledTaskAction -Execute $python -Argument "-m acql.headless --brief" -WorkingDirectory $root
Register-ScheduledTask -TaskName "ACQL Sunday brief" -Action $brief -Settings $wake `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 9:00AM) `
    -Description "ACQL Dashboard: Sunday's top calls, line moves and odds budget, emailed to you." | Out-Null

# Operation Sunday: every 2 hours, 9 AM - 9 PM, so a run always falls inside the
# 3-hour lock window - Thursday's deadline, a Wednesday opener or Thanksgiving noon.
$opsun = New-ScheduledTaskAction -Execute $python -Argument "-m operation_sunday --log run" -WorkingDirectory $root
$opsunTrigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$opsunTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At 9:00AM `
    -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Hours 12)).Repetition
Register-ScheduledTask -TaskName "ACQL Operation Sunday" -Action $opsun -Settings $wake `
    -Trigger $opsunTrigger `
    -Description "ACQL Dashboard: Operation Sunday's shadow forecasts, locked before the Thursday deadline." | Out-Null

Write-Host "  Scheduled:"
Write-Host "    ACQL Daily          every day at 3:00 AM"
Write-Host "    ACQL Game-day poll  Thu/Sun/Mon, every 10 min, 9 AM - midnight"
Write-Host "    ACQL Deadeye email  Tue/Wed/Thu at 12:00 noon"
Write-Host "    ACQL Training       Tue/Wed/Thu at 12:30 PM"
Write-Host "    ACQL Sunday brief   Sun at 9:00 AM"
Write-Host "    ACQL Operation Sunday  daily, every 2 h, 9 AM - 9 PM (locks before Thursday's deadline)"
Write-Host "  Runs while you're signed in to Windows. Log: data\acql-log.txt"
