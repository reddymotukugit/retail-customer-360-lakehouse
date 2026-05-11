Write-Output "Step 1: Finding sqlcmd..."
$sqlcmd160 = "C:\Program Files\Microsoft SQL Server\160\Tools\Binn\sqlcmd.exe"
$sqlcmd150 = "C:\Program Files\Microsoft SQL Server\150\Tools\Binn\sqlcmd.exe"

if (Test-Path $sqlcmd160) {
    $sqlcmd = $sqlcmd160
    Write-Output "Found SQL 2022 sqlcmd"
} elseif (Test-Path $sqlcmd150) {
    $sqlcmd = $sqlcmd150
    Write-Output "Found SQL 2019 sqlcmd"
} else {
    Write-Output "sqlcmd not found, listing SQL Server folder:"
    Get-ChildItem "C:\Program Files\Microsoft SQL Server\" | Select-Object Name
    exit 1
}

Write-Output "Step 2: Enabling mixed auth mode..."
& $sqlcmd -S localhost -E -Q "EXEC xp_instance_regwrite N'HKEY_LOCAL_MACHINE', N'Software\Microsoft\MSSQLServer\MSSQLServer', N'LoginMode', REG_DWORD, 2"

Write-Output "Step 3: Enabling SA login..."
& $sqlcmd -S localhost -E -Q "ALTER LOGIN sa ENABLE;"
& $sqlcmd -S localhost -E -Q "ALTER LOGIN sa WITH PASSWORD = N'RetailLH@2026!';"

Write-Output "Step 4: Finding and restarting SQL service..."
$svc = Get-Service | Where-Object { $_.Name -like "MSSQL*" } | Select-Object -First 1
Write-Output "Service found: $($svc.Name)"
Restart-Service -Name $svc.Name -Force
Start-Sleep -Seconds 15
Write-Output "SQL Server restarted."

Write-Output "Step 5: Registering SHIR..."
$shirKey = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@zfHFjZHhNkGfamX5mA/IBg7eHGNWQPxiM8BUQHzn56I="
$dmgcmd = "C:\Program Files\Microsoft Integration Runtime\5.0\Shared\dmgcmd.exe"
if (Test-Path $dmgcmd) {
    & $dmgcmd -RegisterNewNode $shirKey "vm-shir"
    Write-Output "SHIR registration done."
} else {
    Write-Output "dmgcmd not found, listing IR folder:"
    Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse | Select-Object FullName
}
Write-Output "All steps complete."
