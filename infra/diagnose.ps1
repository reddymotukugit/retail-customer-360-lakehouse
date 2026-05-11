Write-Output "=== SQL Server folder ==="
Get-ChildItem "C:\Program Files\Microsoft SQL Server\" | Select-Object Name

Write-Output "=== SQL Services ==="
Get-Service | Where-Object { $_.DisplayName -like "*SQL*" } | Select-Object Name, DisplayName, Status

Write-Output "=== Integration Runtime folder ==="
Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -ErrorAction SilentlyContinue | Select-Object Name

Write-Output "=== Finding sqlcmd anywhere ==="
Get-ChildItem "C:\Program Files\Microsoft SQL Server\" -Recurse -Filter "sqlcmd.exe" -ErrorAction SilentlyContinue | Select-Object FullName

Write-Output "=== Finding dmgcmd anywhere ==="
Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse -Filter "dmgcmd.exe" -ErrorAction SilentlyContinue | Select-Object FullName
