Write-Output "=== Step 1: Diagnose current state ==="
Write-Output "SQL Server folder:"
Get-ChildItem "C:\Program Files\Microsoft SQL Server\" -ErrorAction SilentlyContinue | Select-Object Name
Write-Output "SQL Services:"
Get-Service | Where-Object { $_.DisplayName -like "*SQL*" } | Select-Object Name, DisplayName, Status
Write-Output "Integration Runtime folder:"
Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -ErrorAction SilentlyContinue | Select-Object Name

Write-Output ""
Write-Output "=== Step 2: Enable mixed auth mode via registry ==="
$regPath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server"
$instances = Get-ChildItem $regPath -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "MSSQL\d+" }
foreach ($inst in $instances) {
    $mssqlPath = "$regPath\$($inst.PSChildName)\MSSQLServer"
    if (Test-Path $mssqlPath) {
        Set-ItemProperty -Path $mssqlPath -Name "LoginMode" -Value 2 -Type DWord
        Write-Output "Set LoginMode=2 (mixed) on $mssqlPath"
    }
}

Write-Output ""
Write-Output "=== Step 3: Restart SQL Server service ==="
$svc = Get-Service | Where-Object { $_.Name -like "MSSQL*" -and $_.Name -notlike "*AGENT*" -and $_.Name -notlike "*BROWSER*" } | Select-Object -First 1
if ($svc) {
    Write-Output "Restarting service: $($svc.Name)"
    Restart-Service -Name $svc.Name -Force
    Start-Sleep -Seconds 20
    Write-Output "Service restarted."
} else {
    Write-Output "ERROR: No SQL Server service found!"
    exit 1
}

Write-Output ""
Write-Output "=== Step 4: Enable SA login using .NET SqlConnection ==="
$maxRetries = 5
$connected = $false
for ($i = 1; $i -le $maxRetries; $i++) {
    try {
        $conn = New-Object System.Data.SqlClient.SqlConnection("Server=localhost;Database=master;Integrated Security=True;Connect Timeout=10;")
        $conn.Open()
        Write-Output "Connected to SQL Server (attempt $i)."
        $connected = $true
        break
    } catch {
        Write-Output "Attempt $i failed: $($_.Exception.Message). Retrying in 10s..."
        Start-Sleep -Seconds 10
    }
}

if (-not $connected) {
    Write-Output "ERROR: Could not connect to SQL Server after $maxRetries attempts."
    exit 1
}

try {
    $queries = @(
        "ALTER LOGIN sa ENABLE;",
        "ALTER LOGIN sa WITH PASSWORD = N'RetailLH@2026!';",
        "EXEC sp_configure 'show advanced options', 1; RECONFIGURE;",
        "EXEC sp_configure 'remote access', 1; RECONFIGURE;"
    )
    foreach ($q in $queries) {
        $cmd = New-Object System.Data.SqlClient.SqlCommand($q, $conn)
        $cmd.ExecuteNonQuery() | Out-Null
        Write-Output "Executed: $q"
    }
    $conn.Close()
    Write-Output "SA login enabled successfully."
} catch {
    Write-Output "SQL error: $($_.Exception.Message)"
    $conn.Close()
    exit 1
}

Write-Output ""
Write-Output "=== Step 5: Final SQL service restart to apply auth mode ==="
Restart-Service -Name $svc.Name -Force
Start-Sleep -Seconds 20
Write-Output "Service restarted."

Write-Output ""
Write-Output "=== Step 6: Test SA login ==="
Start-Sleep -Seconds 5
try {
    $connSA = New-Object System.Data.SqlClient.SqlConnection("Server=localhost;Database=master;User Id=sa;Password=RetailLH@2026!;Connect Timeout=10;")
    $connSA.Open()
    $cmdSA = New-Object System.Data.SqlClient.SqlCommand("SELECT @@VERSION AS ver", $connSA)
    $reader = $cmdSA.ExecuteReader()
    while ($reader.Read()) {
        Write-Output "SA login works! SQL Version: $($reader['ver'])"
    }
    $connSA.Close()
} catch {
    Write-Output "SA login test failed: $($_.Exception.Message)"
}

Write-Output ""
Write-Output "=== Step 7: Open firewall port 1433 ==="
netsh advfirewall firewall add rule name="SQL1433" dir=in action=allow protocol=TCP localport=1433 2>&1
Write-Output "Firewall rule added."

Write-Output ""
Write-Output "=== Step 8: Register SHIR ==="
$shirKey = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@zfHFjZHhNkGfamX5mA/IBg7eHGNWQPxiM8BUQHzn56I="

# Find dmgcmd.exe in all possible locations
$dmgcmd = Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse -Filter "dmgcmd.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName

if ($dmgcmd) {
    Write-Output "Found dmgcmd at: $dmgcmd"
    & $dmgcmd -RegisterNewNode $shirKey "vm-shir"
    Write-Output "SHIR registration command executed."
    Start-Sleep -Seconds 15
    # Check SHIR status
    $shirService = Get-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
    if ($shirService) {
        Write-Output "SHIR service status: $($shirService.Status)"
    }
} else {
    Write-Output "dmgcmd.exe not found! SHIR may not be installed."
    Write-Output "Checking IR folder contents:"
    Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse -ErrorAction SilentlyContinue | Select-Object FullName

    Write-Output ""
    Write-Output "Downloading and installing SHIR..."
    $shirUrl = "https://download.microsoft.com/download/E/4/7/E4771905-1079-445B-8BF9-8A1A075D8A10/IntegrationRuntime_5.44.8984.1.msi"
    $shirInstaller = "C:\SHIR.msi"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $shirUrl -OutFile $shirInstaller -UseBasicParsing
    Write-Output "SHIR download complete. Installing..."
    Start-Process msiexec -ArgumentList "/i C:\SHIR.msi /quiet /norestart" -Wait
    Write-Output "SHIR installed. Waiting 30s..."
    Start-Sleep -Seconds 30

    $dmgcmd = Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse -Filter "dmgcmd.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if ($dmgcmd) {
        Write-Output "Found dmgcmd at: $dmgcmd"
        & $dmgcmd -RegisterNewNode $shirKey "vm-shir"
        Write-Output "SHIR registration done."
    } else {
        Write-Output "ERROR: dmgcmd still not found after install."
    }
}

Write-Output ""
Write-Output "=== All steps complete ==="
