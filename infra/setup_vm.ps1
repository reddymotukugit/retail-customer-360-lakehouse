# Step 1: Download and install SQL Server 2022 Express
Write-Output "Downloading SQL Server 2022 Express..."
$sqlUrl = "https://go.microsoft.com/fwlink/p/?linkid=2216019&clcid=0x409&culture=en-us&country=us"
$sqlInstaller = "C:\SQLServerExpress.exe"
Invoke-WebRequest -Uri $sqlUrl -OutFile $sqlInstaller -UseBasicParsing
Write-Output "Installing SQL Server..."
Start-Process -FilePath $sqlInstaller -ArgumentList "/Q /IACCEPTSQLSERVERLICENSETERMS /ACTION=Install /FEATURES=SQLEngine /INSTANCENAME=MSSQLSERVER /SQLSVCACCOUNT=`"NT AUTHORITY\NETWORK SERVICE`" /SQLSYSADMINACCOUNTS=`"BUILTIN\Administrators`" /TCPENABLED=1 /BROWSERSVCSTARTUPTYPE=Automatic" -Wait
Write-Output "SQL Server installed."

# Step 2: Enable SA login and set password
Write-Output "Enabling SA login..."
Start-Sleep -Seconds 15
sqlcmd -S localhost -E -Q "ALTER LOGIN sa ENABLE; ALTER LOGIN sa WITH PASSWORD = N'RetailLH@2026!'"
Write-Output "SA login enabled."

# Step 3: Restart SQL Server service to apply auth mode change
Restart-Service -Name MSSQLSERVER -Force
Start-Sleep -Seconds 10

# Step 4: Open firewall for SQL Server port 1433
netsh advfirewall firewall add rule name="SQL Server 1433" dir=in action=allow protocol=TCP localport=1433
Write-Output "Firewall rule added."

# Step 5: Download and install SHIR
Write-Output "Downloading SHIR installer..."
$shirUrl = "https://download.microsoft.com/download/E/4/7/E4771905-1079-445B-8BF9-8A1A075D8A10/IntegrationRuntime_5.44.8984.1.msi"
$shirInstaller = "C:\SHIR.msi"
Invoke-WebRequest -Uri $shirUrl -OutFile $shirInstaller -UseBasicParsing
Write-Output "Installing SHIR..."
Start-Process msiexec -ArgumentList "/i C:\SHIR.msi /quiet /norestart" -Wait
Write-Output "SHIR installed."

# Step 6: Register SHIR with ADF key
Start-Sleep -Seconds 30
Write-Output "Registering SHIR with ADF..."
$shirKey = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@zfHFjZHhNkGfamX5mA/IBg7eHGNWQPxiM8BUQHzn56I="
& "C:\Program Files\Microsoft Integration Runtime\5.0\Shared\dmgcmd.exe" -RegisterNewNode $shirKey "vm-shir"
Write-Output "SHIR registered. Setup complete."
