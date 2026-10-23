# Registra la tarea diaria de refresh del dashboard OKRs H2 (10:30 AM).
# El script decide solo que refrescar: siempre diario; lunes suma semanal; dia 1 suma mensual.
$root     = "C:\Users\dana.nabel\Desktop\vs\tribu-b2b-dana"
$python   = "$root\.venv\Scripts\python.exe"
$script   = "$root\tablero-live\h2\refresh_h2.py"
$log      = "$root\tablero-live\h2\refresh_h2.log"
$taskName = "OKRs H2 - Refresh"

$cmd     = "& '$python' '$script' *>> '$log'"
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -Daily -At "10:30AM"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Tarea '$taskName' creada: todos los dias 10:30 (lunes suma semanal, dia 1 suma mensual)." -ForegroundColor Green
Write-Host "Log: $log"
