$dmgcmd  = "C:\Program Files\Microsoft Integration Runtime\5.0\Shared\dmgcmd.exe"
$key2    = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@JDdzU+feZ1sJ0qeYx1ROKhNtC90oX9Iw9KAxw22kVoA="
$node    = "vm-shir"

Write-Output "=== SHIR version ==="
$exe = Get-Item $dmgcmd -ErrorAction SilentlyContinue
if ($exe) { Write-Output "File version: $($exe.VersionInfo.FileVersion)" }

Write-Output ""
Write-Output "=== Network connectivity tests ==="
$hosts = @(
    "adf-retaillh-dev.australiaeast.datafactory.azure.net",
    "australiaeast.frontend.clouddatahub.net",
    "login.microsoftonline.com"
)
foreach ($h in $hosts) {
    try {
        $r = Test-NetConnection -ComputerName $h -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue
        Write-Output "$h : 443 = $r"
    } catch {
        Write-Output "$h : error $($_.Exception.Message)"
    }
}

Write-Output ""
Write-Output "=== Recent SHIR log files ==="
$logDirs = @(
    "C:\ProgramData\Microsoft\Data Management Gateway\5.0\Gateway",
    "$env:USERPROFILE\AppData\Local\Microsoft\Integration Runtime\5.0\Gateway\GatewayLogs",
    "C:\Program Files\Microsoft Integration Runtime\5.0\Gateway\GatewayLogs",
    "C:\Windows\SysWOW64\config\systemprofile\AppData\Local\Microsoft\Integration Runtime\5.0\Gateway\GatewayLogs",
    "C:\Windows\System32\config\systemprofile\AppData\Local\Microsoft\Integration Runtime\5.0\Gateway\GatewayLogs"
)
$foundLog = $false
foreach ($dir in $logDirs) {
    if (Test-Path $dir) {
        Write-Output "Found log dir: $dir"
        $logs = Get-ChildItem $dir -Filter "*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($logs) {
            Write-Output "Latest log: $($logs.FullName) ($($logs.LastWriteTime))"
            $lines = Get-Content $logs.FullName -Tail 40 -ErrorAction SilentlyContinue
            $lines | Where-Object { $_ -match "ERROR|WARN|register|connected|failed|Unauthorized|Forbidden" } | Select-Object -Last 20 | ForEach-Object { Write-Output "  $_" }
            $foundLog = $true
        }
        break
    }
}
if (-not $foundLog) {
    Write-Output "No log directory found. Searching..."
    Get-ChildItem "C:\" -Recurse -Filter "*.log" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -like "*Integration*" -or $_.FullName -like "*Gateway*" } | Select-Object -First 5 | ForEach-Object { Write-Output "  $($_.FullName)" }
}

Write-Output ""
Write-Output "=== Trying re-registration with Key2 ==="
Stop-Service -Name "DIAHostService" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
$proc = Start-Process -FilePath $dmgcmd -ArgumentList "-RegisterNewNode", $key2, $node -Wait -PassThru -NoNewWindow
Write-Output "Key2 exit code: $($proc.ExitCode)"
Start-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 20

$svc = Get-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
if ($svc) { Write-Output "DIAHostService after Key2: $($svc.Status)" }

Write-Output ""
Write-Output "=== Windows Event Log - Integration Runtime errors (last 10) ==="
Get-EventLog -LogName Application -Source "*Integration*" -Newest 10 -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "[$($_.TimeGenerated)] $($_.EntryType): $($_.Message.Substring(0, [Math]::Min(200, $_.Message.Length)))"
}

Write-Output "Done."
