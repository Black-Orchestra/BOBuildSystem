New-Item -ItemType Directory -Force -Path "C:\Temp\"

Write-Host "Downloading Git-2.47.1-64-bit.exe..."
Invoke-WebRequest "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe" `
    -OutFile "C:\Temp\Git-2.47.1-64-bit.exe"

Write-Host "Running Git-2.47.1-64-bit.exe..."
$Proc = Start-Process -FilePath "C:\Temp\Git-2.47.1-64-bit.exe" `
    -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/LOADINF=install_git_options.ini" `
    -NoNewWindow `
    -Wait `
    -PassThru

Write-Host "Done."

exit $Proc.ExitCode
