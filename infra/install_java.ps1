Write-Output "Installing Java 11 JRE for SHIR Parquet support..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$installed = $false

# Method 1: winget (available on Windows Server 2022)
Write-Output "Trying winget..."
try {
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($wg) {
        winget install --id EclipseAdoptium.Temurin.11.JRE --silent --accept-package-agreements --accept-source-agreements 2>&1
        $installed = $true
        Write-Output "winget install completed."
    } else {
        Write-Output "winget not found."
    }
} catch {
    Write-Output "winget failed: $($_.Exception.Message)"
}

# Method 2: Direct MSI download (Temurin 11 JRE)
if (-not $installed) {
    Write-Output "Trying direct MSI download (Temurin 11)..."
    $msi = "C:\jre11.msi"
    $urls = @(
        "https://github.com/adoptium/temurin11-binaries/releases/download/jdk-11.0.22%2B7/OpenJDK11U-jre_x64_windows_hotspot_11.0.22_7.msi",
        "https://corretto.aws/downloads/latest/amazon-corretto-11-x64-windows-jdk.msi"
    )
    foreach ($url in $urls) {
        try {
            Write-Output "Downloading from $url ..."
            Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing -TimeoutSec 120
            $sizeMB = [Math]::Round((Get-Item $msi).Length/1MB,1)
            Write-Output "Downloaded: $sizeMB MB"
            if ($sizeMB -gt 1) {
                $proc = Start-Process "msiexec.exe" -ArgumentList "/i $msi /quiet /norestart ADDLOCAL=FeatureMain" -Wait -PassThru
                Write-Output "Install exit code: $($proc.ExitCode)"
                $installed = $true
                break
            }
        } catch {
            Write-Output "Failed: $($_.Exception.Message)"
        }
    }
}

Start-Sleep -Seconds 10

# Find java.exe and set JAVA_HOME
Write-Output "Searching for java.exe..."
$searchPaths = @(
    "C:\Program Files\Eclipse Adoptium",
    "C:\Program Files\Amazon Corretto",
    "C:\Program Files\Java",
    "C:\Program Files\Microsoft"
)
$javaExe = $null
foreach ($base in $searchPaths) {
    if (Test-Path $base) {
        $javaExe = Get-ChildItem $base -Recurse -Filter "java.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
        if ($javaExe) { break }
    }
}

# Also try a broader search
if (-not $javaExe) {
    $javaExe = Get-ChildItem "C:\Program Files" -Recurse -Filter "java.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
}

if ($javaExe) {
    Write-Output "Found java.exe: $javaExe"
    $javaHome = Split-Path (Split-Path $javaExe)
    Write-Output "JAVA_HOME: $javaHome"
    [System.Environment]::SetEnvironmentVariable("JAVA_HOME", $javaHome, "Machine")
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    if ($machinePath -notlike "*$javaHome\bin*") {
        [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$javaHome\bin", "Machine")
    }
    $env:JAVA_HOME = $javaHome
    $env:Path = "$env:Path;$javaHome\bin"
    $ver = & $javaExe -version 2>&1
    Write-Output "Java version: $ver"
} else {
    Write-Output "ERROR: java.exe not found. Trying choco as last resort..."
    # Try chocolatey
    try {
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
        iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        choco install temurin11jre -y --no-progress
        $javaExe = Get-ChildItem "C:\Program Files\Eclipse Adoptium" -Recurse -Filter "java.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
        if ($javaExe) {
            $javaHome = Split-Path (Split-Path $javaExe)
            [System.Environment]::SetEnvironmentVariable("JAVA_HOME", $javaHome, "Machine")
            Write-Output "Installed via choco. JAVA_HOME=$javaHome"
        }
    } catch {
        Write-Output "Choco also failed: $($_.Exception.Message)"
        exit 1
    }
}

Write-Output "Restarting SHIR..."
Restart-Service -Name "DIAHostService" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 15
$svc = Get-Service -Name "DIAHostService" -ErrorAction SilentlyContinue
if ($svc) { Write-Output "DIAHostService: $($svc.Status)" }
Write-Output "Done."
