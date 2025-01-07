# Installs all dependencies and creates a Python production
# virtual environment in the repo root called 'bo_venv'.

# TODO: can we make this runnable as non-admin?

# TODO: this does not work properly on systems with multiple Python versions installed!
#       - modify install_python.ps1 to use explicit Python installation path?

Write-Output "Installing Python..."
& "$PSScriptRoot\setup\install_python.ps1"

Write-Output "Installing VC Redist..."
& "$PSScriptRoot\setup\install_vc_redist.ps1"

Write-Output "Ensuring Python Scripts are in PATH..."
$PythonPath = (Get-Command python).Source
$PythonScriptsPath = Join-Path -Path (Split-Path -Path $PythonPath -Parent) -ChildPath "\Scripts\"
if ( [System.IO.Directory]::Exists($PythonScriptsPath))
{
    if (-Not ($Env:Path -Split ";" -Contains $PythonScriptsPath))
    {
        [Environment]::SetEnvironmentVariable(
                "Path",
                [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Machine) + $PythonScriptsPath,
                [System.EnvironmentVariableTarget]::Machine)
    }
}

Write-Output "Installing Python packages if requirements.txt exists..."
if ( [System.IO.File]::Exists("$PSScriptRoot\DataTools\requirements.txt"))
{
    Start-Process -FilePath "python.exe" `
        -ArgumentList "-m", "ensurepip" `
        -Wait `
        -NoNewWindow
    Start-Process -FilePath "python.exe" `
        -ArgumentList "-m", "pip", "install", "--upgrade", "pip" `
        -Wait `
        -NoNewWindow
    #    Start-Process -FilePath "python.exe" `
    #        -ArgumentList "-m", "pip", "install", "-r", "$PSScriptRoot\DataTools\requirements.txt" `
    #        -Wait `
    #        -NoNewWindow
}

Write-Output "Done."
