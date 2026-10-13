# Windows Task Scheduler entry point: powershell -File scripts\weekly_job.ps1 [-Freeze]
param([switch]$Freeze)
Set-Location (Join-Path $PSScriptRoot "..")
if ($Freeze) { python -m nflpickem weekly --freeze } else { python -m nflpickem weekly }
