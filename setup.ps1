# Installs all dependencies and creates a Python production
# virtual environment in the repo root called 'bo_venv'.

# TODO: can we make this runnable as non-admin?

# TODO: this does not work properly on systems with multiple Python versions installed!
#       - modify install_python.ps1 to use explicit Python installation path?

Write-Output "Installing Python..."
& "$PSScriptRoot\setup\install_python.ps1"

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

# TODO: use bobuild tools to install RS2 server, game and SDK.

Write-Output "Setting RS2 server firewall rules..."
& "$PSScriptRoot\setup\allow_rs2_server_firewall.ps1"

Write-Output "Done."
