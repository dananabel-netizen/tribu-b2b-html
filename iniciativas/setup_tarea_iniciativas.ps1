# Registra la tarea diaria de refresh del dashboard Iniciativas (10:45 AM).
$root     = "C:\Users\dana.nabel\Desktop\vs\tribu-b2b-dana"
$python   = "$root\.venv\Scripts\python.exe"
$script   = "$root\tablero-live\iniciativas\refresh_iniciativas.py"
$log      = "$root\tablero-live\iniciativas\refresh_iniciativas.log"
$taskName = "Iniciativas HotelDO - Refresh"

$cmd     = "& '$python' '$script' *>> '$log'"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -Daily -At "10:45AM"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Tarea '$taskName' creada: todos los dias 10:45." -ForegroundColor Green
Write-Host "Log: $log"
