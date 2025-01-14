$ErrorView = 'NormalView'

$DX_WEB_SETUP = "C:\Temp\dxwebsetup.exe"

New-Item "C:\Temp\" -ItemType Directory -ErrorAction SilentlyContinue

if (Test-Path $DX_WEB_SETUP)
{
    Write-Output "'$DX_WEB_SETUP' exists."
}
else
{
    Write-Output "Downloading dxwebsetup.exe..."
    Invoke-WebRequest `
        -Uri https://download.microsoft.com/download/1/7/1/1718CCC4-6315-4D8E-9543-8E28A4E18C4C/dxwebsetup.exe `
        -OutFile $DX_WEB_SETUP
}

$DxWebSetupTemp = "C:\Temp\dx_websetup_temp\"
New-Item $DxWebSetupTemp -ItemType Directory -ErrorAction SilentlyContinue

Write-Host "Running dxwebsetup.exe..."
Start-Process -FilePath $DX_WEB_SETUP `
    -NoNeWindow `
    -Wait `
    -ArgumentList "/Q", "/T:$DxWebSetupTemp"

$DX_REDIST_EXE = "C:\Temp\dx_redist.exe"

if (Test-Path $DX_REDIST_EXE)
{
    Write-Output "'$DX_REDIST_EXE' exists"
}
else
{
    Write-Output "Downloading directx_Jun2010_redist.exe..."
    Invoke-WebRequest `
    -Uri https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe `
    -OutFile $DX_REDIST_EXE
}

$DxRedistTemp = "C:\Temp\dx_redist_temp\"
Write-Output "Running $DX_REDIST_EXE..."
Start-Process -FilePath $DX_REDIST_EXE `
    -NoNewWindow `
    -ArgumentList "/Q", "/T:$DxRedistTemp"

Wait-Process -Id (Get-Process dx_redist).id

Write-Output "Running DXSETUP.exe..."
Start-Process -FilePath $DxRedistTemp\DXSETUP.exe `
    -NoNewWindow `
    -Wait `
    -ArgumentList "/Silent"

Exit $LASTEXITCODE
