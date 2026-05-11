$shirKey  = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@zfHFjZHhNkGfamX5mA/IBg7eHGNWQPxiM8BUQHzn56I="
$dmgcmd   = "C:\Program Files\Microsoft Integration Runtime\5.0\Shared\dmgcmd.exe"
$nodeName = "vm-shir"

Write-Output "Step 1: Test outbound connectivity to ADF endpoint"
try {
    $result = Test-NetConnection -ComputerName "adf-retaillh-dev.australiaeast.datafactory.azure.net" -Port 443 -InformationLevel Quiet
    if ($result) {
        Write-Output "Port 443 reachable: YES"
    } else {
        Write-Output "Port 443 reachable: NO"
    }
} catch {
    Write-Output "Connectivity test error: $($_.Exception.Message)"
}

Write-Output "Step 2: Stop SHIR services"
$svcNames = @("DIAHostService")
foreach ($svcName in $svcNames) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Output "Stopping $svcName current=$($svc.Status)"
        Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
    } else {
        Write-Output "Service $svcName not found"
    }
}

Write-Output "Step 3: Re-register SHIR"
if (-not (Test-Path $dmgcmd)) {
    Write-Output "ERROR: dmgcmd.exe not found"
    exit 1
}

Write-Output "Running dmgcmd RegisterNewNode..."
$proc = Start-Process -FilePath $dmgcmd -ArgumentList "-RegisterNewNode", $shirKey, $nodeName -Wait -PassThru -NoNewWindow
Write-Output "dmgcmd exit code: $($proc.ExitCode)"

Start-Sleep -Seconds 10

Write-Output "Step 4: Start SHIR services"
foreach ($svcName in $svcNames) {
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
    if ($svc) {
        Start-Service -Name $svcName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
        $svc.Refresh()
        Write-Output "$svcName status after start: $($svc.Status)"
    }
}

Write-Output "Step 5: Waiting 30s for SHIR to phone home to ADF..."
Start-Sleep -Seconds 30

Write-Output "Step 6: Final service status"
Get-Service | Where-Object { $_.DisplayName -like "*Integration Runtime*" -or $_.Name -eq "DIAHostService" } | ForEach-Object {
    Write-Output "  $($_.Name) / $($_.DisplayName) = $($_.Status)"
}

Write-Output "Done. Check ADF Studio in 1-2 minutes."
