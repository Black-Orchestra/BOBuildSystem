# Installs all dependencies and creates a Python production
# virtual environment in the repo root called 'venv'.

# TODO: can we make this runnable as non-admin?

# TODO: this does not work properly on systems with multiple Python versions installed!
#       - modify install_python.ps1 to use explicit Python installation path?

param (
    [Parameter(Position = 0, mandatory = $false)]
    [ValidateSet("FullInstall", "SteamAppInstallOnly")]
    [string]$Action = "FullInstall"
)

# https://github.com/PowerShell/PowerShell/issues/2138
$ProgressPreference = "SilentlyContinue"
$ErrorActionPreference = "Stop"

function CheckExitCode
{
    param (
        [Parameter(Mandatory)]
        [int]$ExitCode
    )

    if ($ExitCode -ne 0)
    {
        throw "Failed with exit code: ${ExitCode}"
    }
}

function SteamAppInstall()
{
    # NOTE: using sleeps here to avoid spamming steamcmd less.
    # There seem to be some errors with hitting the rate limit sometimes.

    Write-Output "Installing RS2..."
    $Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd.py", "install_rs2" `
    -NoNewWindow `
    -Wait `
    -PassThru
    CheckExitCode($Proc.ExitCode)

    Write-Debug "Sleeping for 5 seconds..."; Start-Sleep -Seconds 5

    Write-Output "Installing RS2 SDK.."
    $Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd.py", "install_rs2_sdk" `
    -NoNewWindow `
    -Wait `
    -PassThru
    CheckExitCode($Proc.ExitCode)

    Write-Debug "Sleeping for 5 seconds..."; Start-Sleep -Seconds 5

    Write-Output "Installing RS2 Dedicated Server..."
    $Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd.py", "install_rs2_server" `
    -NoNewWindow `
    -Wait `
    -PassThru
    CheckExitCode($Proc.ExitCode)
}

if ($Action -eq "SteamAppInstallOnly")
{
    SteamAppInstall
    exit $LASTEXITCODE
}

Write-Output "Installing Docker..."
& "$PSScriptRoot\setup\install_docker.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing Python..."
& "$PSScriptRoot\setup\install_python.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing Nuget provider..."
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force
CheckExitCode($LASTEXITCODE)

Write-Output "Installing VC Redist..."
& "$PSScriptRoot\setup\install_vc_redist.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing DirectX Redist..."
& "$PSScriptRoot\setup\install_dx_redist.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing Git..."
& "$PSScriptRoot\setup\install_git.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing TortoiseHG..."
& "$PSScriptRoot\setup\install_tortoisehg.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing UE3ShaderCachePatcherCLI..."
& "$PSScriptRoot\setup\install_shadercachepatcher.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Installing SteamCMD..."
& "$PSScriptRoot\setup\install_steamcmd.ps1"
# CheckExitCode($LASTEXITCODE) NOTE: skipping this check on purpose!
# SteamCMD exit codes are unpredictable.
$LASTEXITCODE = 0

Write-Output "Installing steamguard-cli..."
& "$PSScriptRoot\setup\install_steamguardcli.ps1"
CheckExitCode($LASTEXITCODE)

Write-Output "Install steamguard-cli maFiles manually in '${Env:APPDATA}\steamguard-cli\'!"

Write-Output "Refreshing PATH..."
$Env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") `
    + "; " + [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Output "Ensuring Python Scripts are in PATH..."
$PythonPath = (Get-Command python).Source
$PythonScriptsPath = Join-Path -Path (Split-Path -Path $PythonPath -Parent) -ChildPath "\Scripts\"
if ( [System.IO.Directory]::Exists($PythonScriptsPath))
{
    if (-Not ($Env:Path -Split ";" -Contains $PythonScriptsPath))
    {
        [Environment]::SetEnvironmentVariable(
                "Path",
                [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User) + $PythonScriptsPath,
                [System.EnvironmentVariableTarget]::User)
    }
}

# TODO: check if venv exists already?
Write-Output "Creating Python virtual environment..."
$Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "venv", "venv" `
    -NoNewWindow `
    -Wait `
    -PassThru
CheckExitCode($Proc.ExitCode)

Write-Output "Activating venv..."
& "$PSScriptRoot\venv\Scripts\activate.ps1"

Write-Output "Installing bobuild Python module..."
$Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "ensurepip" `
    -Wait `
    -NoNewWindow `
    -PassThru
CheckExitCode($Proc.ExitCode)
$Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "pip", "install", "--upgrade", "pip" `
    -Wait `
    -NoNewWindow `
    -PassThru
CheckExitCode($Proc.ExitCode)
$Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "pip", "install", "-e", "$PSScriptRoot[dev]" `
    -Wait `
    -NoNewWindow `
    -PassThru
CheckExitCode($Proc.ExitCode)

Write-Output "Setting RS2 server firewall rules..."
& "$PSScriptRoot\setup\allow_rs2_server_firewall.ps1"

Write-Output "Ensuring Mercurial config is correct..."
$Proc = Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/hg.py", "configure" `
    -NoNewWindow `
    -Wait `
    -PassThru
CheckExitCode($Proc.ExitCode)

SteamAppInstall

Write-Output "Done."
