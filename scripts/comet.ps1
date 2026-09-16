# Existing-host shortcuts. No new forecast or public deployment.
# Refresh reuses/creates plans through the existing unchanged pipeline.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)][ValidateSet('start', 'refresh', 'status')][string]$Action = 'status',
    [string]$OperationsRoot = 'D:/Personal/fpl-operations',
    [string]$PlanBase
)
$ErrorActionPreference = 'Stop'
$checkout = Split-Path -Parent $PSScriptRoot
$operations = (Resolve-Path -LiteralPath $OperationsRoot).Path
$python = (Resolve-Path -LiteralPath (Join-Path $operations '.venv/Scripts/python.exe')).Path
$database = (Resolve-Path -LiteralPath (Join-Path $operations 'data/sdp-primary-v2.duckdb')).Path
$runs = Join-Path $operations 'dashboard-runs'
$forecasts = Join-Path $operations 'predictions'
$plans = Join-Path $operations 'dashboard-plans'
$public = Join-Path $checkout 'dashboard/public'
if (-not $PlanBase) { $PlanBase = Join-Path $operations 'plan-server' }

# A stale editable install must fail before touching a database or launching a server.
@'
from pathlib import Path
import sys
from fpl.config import repo_root
if repo_root().resolve() != Path(sys.argv[1]).resolve():
    raise SystemExit("Python imports a different checkout")
'@ | & $python - $checkout
if ($LASTEXITCODE -ne 0) { throw 'Wrong Python checkout; inspect the operational editable install.' }

Push-Location -LiteralPath $checkout
try {
    if ($Action -eq 'refresh') {
        if ($PSCmdlet.ShouldProcess($database, 'Run the existing complete dashboard refresh')) {
            & $python -m fpl.jobs.refresh_dashboard --db $database --runs $runs `
                --forecast-dir $forecasts --preview-public $public --plan-store $plans
            if ($LASTEXITCODE -ne 0) { throw "Dashboard refresh failed ($LASTEXITCODE); inspect its receipt." }
        }
    } elseif ($Action -eq 'status') {
        & $python -m fpl.jobs.sdp_capture_health --db $database --runs $runs --max-success-age-hours 8
        if ($LASTEXITCODE -ne 0) { throw 'Capture health check failed; inspect the retained receipts.' }
        Get-ScheduledTaskInfo -TaskName 'The Comet FPL - SDP primary V2' |
            Select-Object LastRunTime, LastTaskResult, NextRunTime
    } else {
        # Reuse the operational registry/hash selector, never a filename, mtime or GW guess.
        $selection = @'
import json, sys
from pathlib import Path
from fpl.jobs.refresh_dashboard import latest_primary
path, season, run_id = latest_primary(Path(sys.argv[1]), Path(sys.argv[2]))
print(json.dumps({"path": str(path), "run_id": run_id}))
'@ | & $python - $database $forecasts
        if ($LASTEXITCODE -ne 0) { throw 'No verified registered primary; do not start against an older forecast.' }
        $forecast = ($selection | ConvertFrom-Json).path
        $node = (Get-Command node.exe -ErrorAction Stop).Source
        $vite = (Resolve-Path -LiteralPath (Join-Path $checkout 'dashboard/node_modules/vite/bin/vite.js')).Path
        if (-not (Test-Path -LiteralPath (Join-Path $checkout 'dashboard/dist/index.html'))) {
            throw 'Dashboard build missing. Run npm.cmd run build from dashboard first.'
        }
        $services = @(
            @{ Name='dashboard'; Port=4173; Execute=$node; Cwd=(Join-Path $checkout 'dashboard');
               Args=('"{0}" preview --host 127.0.0.1 --port 4173 --strictPort' -f $vite);
               Bindings=@($vite) },
            @{ Name='optimizer'; Port=8765; Execute=$python; Cwd=$checkout;
               Args=('-m fpl.jobs.plan_server --host 127.0.0.1 --port 8765 --base "{0}" --forecast "{1}" --dashboard-data "{2}"' -f $PlanBase,$forecast,(Join-Path $public 'data'));
               Bindings=@($forecast, $PlanBase, (Join-Path $public 'data')) }
        )
        foreach ($service in $services) {
            $listener = Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue
            if ($listener) {
                $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener[0].OwningProcess)"
                $mismatched = @($service.Bindings | Where-Object {
                    -not $process.CommandLine -or -not $process.CommandLine.Contains($_)
                })
                if ($mismatched.Count) {
                    throw "Port $($service.Port) belongs to a different server/vintage. Inspect it before restarting; nothing was stopped."
                }
                Write-Output "$($service.Name) already running: http://127.0.0.1:$($service.Port)/"
                continue
            }
            if ($PSCmdlet.ShouldProcess($service.Name, "Start hidden: $($service.Execute) $($service.Args)")) {
                $logs = Join-Path $operations 'services'
                New-Item -ItemType Directory -Path $logs -Force | Out-Null
                $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
                $prefix = Join-Path $logs ($service.Name+'-'+$stamp)
                $started = Start-Process -FilePath $service.Execute -ArgumentList $service.Args `
                    -WorkingDirectory $service.Cwd -WindowStyle Hidden -PassThru `
                    -RedirectStandardOutput ($prefix+'.out.log') -RedirectStandardError ($prefix+'.err.log')
                Write-Output "$($service.Name) launched (PID $($started.Id)): http://127.0.0.1:$($service.Port)/; logs $prefix"
            }
        }
    }
} finally {
    Pop-Location
}
