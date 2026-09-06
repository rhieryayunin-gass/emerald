$ErrorActionPreference = "Stop"

param(
    [string]$ApiBaseUrl = "https://api-emerald.albiagent.com"
)

$SecureToken = Read-Host "Enter the dedicated EMERALD API token" -AsSecureString
$ApiToken = [System.Net.NetworkCredential]::new("", $SecureToken).Password
if (-not $ApiToken -or $ApiToken.Length -lt 32) {
    throw "A valid dedicated EMERALD API token is required."
}

$Headers = @{ Authorization = "Bearer $ApiToken" }

try {
    $Health = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/health" -Headers $Headers
    $Readiness = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/telemetry/readiness" -Headers $Headers
    $ShadowMetrics = Invoke-RestMethod -Method Get -Uri "$ApiBaseUrl/shadow/metrics" -Headers $Headers
}
catch {
    throw "Brain API is unreachable or rejected the request: $($_.Exception.Message)"
}

Write-Host "RIRI EMERALD API" -ForegroundColor Cyan
$Health | ConvertTo-Json -Depth 6
Write-Host ""
Write-Host "TELEMETRY READINESS" -ForegroundColor Cyan
$Readiness | ConvertTo-Json -Depth 10
Write-Host ""
Write-Host "SHADOW DATASET METRICS" -ForegroundColor Cyan
$ShadowMetrics | ConvertTo-Json -Depth 10

if ($Readiness.telemetry_ready) {
    Write-Host "Telemetry is ready. Tick and heartbeat data are live." -ForegroundColor Green
}
else {
    Write-Host "Telemetry is not ready. Review the blockers above." -ForegroundColor Yellow
}

if (-not $Readiness.entry_ready) {
    Write-Host "Entry remains locked; this is expected before probability calibration." -ForegroundColor Yellow
}

if (-not $ShadowMetrics.calibration_ready) {
    Write-Host "Calibration is not ready; shadow collection remains active and order entry remains locked." -ForegroundColor Yellow
}

$ApiToken = $null
$SecureToken.Dispose()
