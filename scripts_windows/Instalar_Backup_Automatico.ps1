$ErrorActionPreference = 'Stop'

$taskName = 'FinanPE_Backup_Automatico'
$root = [System.IO.Path]::GetFullPath((Join-Path -Path $PSScriptRoot -ChildPath '..'))
$launcher = Join-Path -Path $root -ChildPath 'scripts_windows\Agendador_Backup_Pendrive.bat'
$python = Join-Path -Path $root -ChildPath 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Launcher de backup não encontrado: $launcher"
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python da venv não encontrado: $python"
}

$userSecret = [Environment]::GetEnvironmentVariable('DJANGO_SECRET_KEY', 'User')
$machineSecret = [Environment]::GetEnvironmentVariable('DJANGO_SECRET_KEY', 'Machine')
if ([string]::IsNullOrWhiteSpace($userSecret) -and [string]::IsNullOrWhiteSpace($machineSecret)) {
    throw 'DJANGO_SECRET_KEY persistente não encontrada em User ou Machine; instalação interrompida.'
}

$action = New-ScheduledTaskAction `
    -Execute $env:ComSpec `
    -Argument "/d /c `"$launcher`""
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances Ignore `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType InteractiveToken `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Executa o backup diário do FinanPE e tenta novamente em caso de falha.' `
    -Force | Out-Null

Write-Output "Tarefa agendada '$taskName' registrada/atualizada com cadência horária."
