Write-Output "Checking existing SQL Server installations..."
Get-ChildItem "C:\Program Files\Microsoft SQL Server\" -ErrorAction SilentlyContinue | Select-Object Name
Get-Service | Where-Object { $_.DisplayName -like "*SQL*" } | Select-Object Name, DisplayName, Status

Write-Output "Downloading SQL Server 2022 Express (direct EXE)..."
$url = "https://download.microsoft.com/download/3/8/d/38de7036-2433-4207-8eae-06e247e17b25/SQLEXPR_x64_ENU.exe"
$installer = "C:\SQLEXPR_x64_ENU.exe"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
Write-Output "Download complete. File size: $((Get-Item $installer).Length / 1MB) MB"

Write-Output "Installing SQL Server 2022 Express..."
$args = '/Q /IACCEPTSQLSERVERLICENSETERMS /ACTION=Install /FEATURES=SQLEngine /INSTANCENAME=MSSQLSERVER /SQLSVCACCOUNT="NT AUTHORITY\NETWORK SERVICE" /SQLSYSADMINACCOUNTS="BUILTIN\Administrators" /SECURITYMODE=SQL /SAPWD="RetailLH@2026!" /TCPENABLED=1 /BROWSERSVCSTARTUPTYPE=Automatic'
Start-Process -FilePath $installer -ArgumentList $args -Wait -NoNewWindow
Write-Output "Installation process completed."

Write-Output "Checking services after install..."
Get-Service | Where-Object { $_.DisplayName -like "*SQL*" } | Select-Object Name, DisplayName, Status

Write-Output "Opening firewall port 1433..."
netsh advfirewall firewall add rule name="SQL1433" dir=in action=allow protocol=TCP localport=1433
Write-Output "Done."
