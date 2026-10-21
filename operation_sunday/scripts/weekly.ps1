# Daily in season (Task Scheduler). Acts on the next unlocked week; a no-op once locked.
Set-Location (Join-Path $PSScriptRoot "..\..")
python -m operation_sunday run
python -m operation_sunday check-deadline
if ($LASTEXITCODE -ne 0) { Write-Warning "Operation Sunday: a Thursday deadline was missed or locked late" }
