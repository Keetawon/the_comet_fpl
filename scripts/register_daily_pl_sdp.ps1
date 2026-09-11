# Registers a current-user, logged-in local task. -WhatIf performs validation only.
# Persistent Python must already have this checkout installed; this script installs nothing.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [Parameter(Mandatory = $true)][string]$RunRoot,
    [string]$At = '07:00',
    [string]$TaskName = 'The Comet FPL - daily SDP',
    [switch]$RawOnly,
    [switch]$Workload
)
$ErrorActionPreference = 'Stop'
$python = (Resolve-Path -LiteralPath $PythonPath).Path
$database = (Resolve-Path -LiteralPath $DatabasePath).Path
$checkout = Split-Path -Parent $PSScriptRoot
$runs = [IO.Path]::GetFullPath($RunRoot)
if ($python -match '(?i)[\\/]temp[\\/]' -or $database -match '(?i)[\\/]temp[\\/]' -or $runs -match '(?i)[\\/]temp[\\/]') {
    throw 'Use persistent Python and operational storage, not a temporary directory.'
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Task already exists: $TaskName. Inspect it explicitly; no existing task was overwritten."
}
$clock = [TimeSpan]::ParseExact($At, 'hh\:mm', [Globalization.CultureInfo]::InvariantCulture)
$arguments = '-m fpl.jobs.daily_pl_sdp --db "{0}" --runs "{1}"' -f $database, $runs
if ($RawOnly) { $arguments += ' --raw-only' }
if ($Workload) { $arguments += ' --workload' }
# pythonw prevents an unwanted console window during an interactive-user scheduled run.
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw 'This Windows task requires pythonw.exe beside the supplied permanent python.exe.'
}
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $checkout
$trigger = New-ScheduledTaskTrigger -Daily -At ([DateTime]::Today.Add($clock))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive -RunLevel Limited
if ($PSCmdlet.ShouldProcess($TaskName, "Register daily at $At local time ($arguments)")) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description 'Local SDP capture, revisions, backup and freshness; requires signed-in owner. No forecasts.'
}
