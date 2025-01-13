# Installs all dependencies and creates a Python production
# virtual environment in the repo root called 'bo_venv'.

# TODO: can we make this runnable as non-admin?

# TODO: this does not work properly on systems with multiple Python versions installed!
#       - modify install_python.ps1 to use explicit Python installation path?

$ErrorActionPreference = "Stop"

Write-Output "Installing Python..."
& "$PSScriptRoot\setup\install_python.ps1"

Write-Output "Installing Nuget provider..."
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force

Write-Output "Installing VC Redist..."
& "$PSScriptRoot\setup\install_vc_redist.ps1"

Write-Output "Installing Git..."
& "$PSScriptRoot\setup\install_git.ps1"

Write-Output "Installing TortoiseHG..."
& "$PSScriptRoot\setup\install_tortoisehg.ps1"

Write-Output "Installing UE3ShaderCachePatcherCLI..."
& "$PSScriptRoot\setup\install_shadercachepatcher.ps1"

Write-Output "Installing SteamCMD..."
& "$PSScriptRoot\setup\install_steamcmd.ps1"

Write-Output "Installing steamguard-cli..."
& "$PSScriptRoot\setup\install_steamguardcli.ps1"

Write-Output "Install steamguard-cli maFiles manually in '${Env:APPDATA}\steamguard-cli\'!"

Write-Output "Refreshing PATH..."
$Env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") `
    + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

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

Write-Output "Creating Python virtual environment..."
Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "venv", "venv" `
    -NoNewWindow `
    -Wait

Write-Output "Activating venv..."
& "$PSScriptRoot\venv\Scripts\activate.ps1"

Write-Output "Installing bobuild Python module..."
Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "ensurepip" `
    -Wait `
    -NoNewWindow
Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "pip", "install", "--upgrade", "pip" `
    -Wait `
    -NoNewWindow
Start-Process -FilePath "python.exe" `
    -ArgumentList "-m", "pip", "install", "$PSScriptRoot" `
    -Wait `
    -NoNewWindow

Write-Output "Installing RS2..."
Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd/main.py", "install_rs2" `
    -NoNewWindow `
    -Wait

Write-Output "Installing RS2 SDK.."
Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd/main.py", "install_rs2_sdk" `
    -NoNewWindow `
    -Wait

Write-Output "Installing RS2 Dedicated Server..."
Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/steamcmd/main.py", "install_rs2_server" `
    -NoNewWindow `
    -Wait

Write-Output "Ensuring Mercurial config is correct..."
Start-Process -FilePath "python.exe" `
    -ArgumentList "$PSScriptRoot/bobuild/hg/main.py", "ensure_config" `
    -NoNewWindow `
    -Wait

Write-Output "Setting RS2 server firewall rules..."
& "$PSScriptRoot\setup\allow_rs2_server_firewall.ps1"

Write-Output "Done."
