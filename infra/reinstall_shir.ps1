$key1    = "IR@0f66ecca-b37d-4048-8532-0e584a6aca6f@adf-retaillh-dev@ServiceEndpoint=adf-retaillh-dev.australiaeast.datafactory.azure.net@zfHFjZHhNkGfamX5mA/IBg7eHGNWQPxiM8BUQHzn56I="
$node    = "vm-shir"

Write-Output "Step 1: Stop all SHIR services"
$shirSvcs = @("DIAHostService", "DMGUpgradeService")
foreach ($s in $shirSvcs) {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne "Stopped") {
        Stop-Service -Name $s -Force -ErrorAction SilentlyContinue
        Write-Output "  Stopped $s"
    }
}
Start-Sleep -Seconds 8

Write-Output "Step 2: Uninstall existing SHIR"
$shirProduct = Get-WmiObject -Class Win32_Product -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "*Integration Runtime*" }
if ($shirProduct) {
    Write-Output "  Found: $($shirProduct.Name) $($shirProduct.Version)"
    $shirProduct.Uninstall() | Out-Null
    Write-Output "  Uninstalled."
} else {
    Write-Output "  Not found via WMI, trying registry uninstall..."
    $uninstallKeys = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall" |
        Get-ItemProperty | Where-Object { $_.DisplayName -like "*Integration Runtime*" }
    foreach ($key in $uninstallKeys) {
        Write-Output "  Found: $($key.DisplayName)"
        if ($key.UninstallString) {
            $uninst = $key.UninstallString -replace "MsiExec.exe", "" -replace "/I", "/X"
            Start-Process "msiexec.exe" -ArgumentList "$uninst /quiet /norestart" -Wait
            Write-Output "  Uninstall command executed."
        }
    }
}
Start-Sleep -Seconds 15

Write-Output "Step 3: Clean up residual registry keys"
$regPaths = @(
    "HKLM:\SOFTWARE\Microsoft\DataTransfer\DataManagementGateway",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\DataTransfer\DataManagementGateway"
)
foreach ($rp in $regPaths) {
    if (Test-Path $rp) {
        Remove-Item $rp -Recurse -Force -ErrorAction SilentlyContinue
        Write-Output "  Removed registry: $rp"
    }
}

Write-Output "Step 4: Clean up leftover files"
$dirs = @(
    "C:\Program Files\Microsoft Integration Runtime",
    "C:\ProgramData\Microsoft\DataManagementGateway"
)
foreach ($d in $dirs) {
    if (Test-Path $d) {
        Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
        Write-Output "  Removed dir: $d"
    }
}

Write-Output "Step 5: Download latest SHIR (5.64)"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$shirMsi = "C:\SHIR_latest.msi"
# Use the official redirect URL for latest SHIR
$url = "https://download.microsoft.com/download/E/4/7/E4771905-1079-445B-8BF9-8A1A075D8A10/IntegrationRuntime_5.64.9558.1.msi"
Write-Output "  Downloading from $url ..."
try {
    Invoke-WebRequest -Uri $url -OutFile $shirMsi -UseBasicParsing
    Write-Output "  Downloaded: $((Get-Item $shirMsi).Length / 1MB) MB"
} catch {
    Write-Output "  Direct URL failed, trying redirect URL..."
    $url2 = "https://go.microsoft.com/fwlink/?linkid=839822"
    Invoke-WebRequest -Uri $url2 -OutFile $shirMsi -UseBasicParsing
    Write-Output "  Downloaded via redirect: $((Get-Item $shirMsi).Length / 1MB) MB"
}

Write-Output "Step 6: Install SHIR"
$proc = Start-Process "msiexec.exe" -ArgumentList "/i $shirMsi /quiet /norestart" -Wait -PassThru
Write-Output "  Install exit code: $($proc.ExitCode)"
Start-Sleep -Seconds 30

Write-Output "Step 7: Verify install"
$dmgcmd = Get-ChildItem "C:\Program Files\Microsoft Integration Runtime\" -Recurse -Filter "dmgcmd.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if ($dmgcmd) {
    $ver = (Get-Item $dmgcmd).VersionInfo.FileVersion
    Write-Output "  dmgcmd found: $dmgcmd (version $ver)"
} else {
    Write-Output "  ERROR: dmgcmd not found after install"
    exit 1
}

Write-Output "Step 8: Register with Key1"
$proc2 = Start-Process -FilePath $dmgcmd -ArgumentList "-RegisterNewNode", $key1, $node -Wait -PassThru -NoNewWindow
Write-Output "  Registration exit code: $($proc2.ExitCode)"
Start-Sleep -Seconds 15

Write-Output "Step 9: Start services and wait"
Start-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 30
$svc = Get-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
if ($svc) { Write-Output "  DIAHostService: $($svc.Status)" }

Write-Output "Done. Wait 2 minutes then check ADF Studio."
