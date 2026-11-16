# Registra la tarea que atiende el boton "Actualizar" del tablero OKRs H2: cada 5 min mira si hay un
# pedido nuevo (refresh_h2.py --pedido). Si no hay, no hace nada (solo un git fetch). Si hay, refresca todo.
$root     = "C:\Users\dana.nabel\Desktop\vs\tribu-b2b-dana"
$python   = "$root\.venv\Scripts\python.exe"
$script   = "$root\tablero-live\h2\refresh_h2.py"
$log      = "$root\tablero-live\h2\refresh_h2_pedido.log"
$taskName = "OKRs H2 - Pedido Actualizar"

$cmd      = "& '$python' '$script' --pedido *>> '$log'"
$action   = New-ScheduledTaskAction -Execute "powershell.exe" `
              -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$cmd`""
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force | Out-Null

Write-Host "Tarea '$taskName' creada: cada 5 min atiende pedidos del boton Actualizar." -ForegroundColor Green
Write-Host "Log: $log"
