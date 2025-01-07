Write-Host "Ensuring long path support is enabled..."
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name "LongPathsEnabled" `
    -Value 1

New-Item -ItemType Directory -Force -Path "C:\Temp\"

Write-Host "Downloading python-3.13.1-amd64.exe..."
Invoke-WebRequest "https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe" `
    -OutFile "C:\Temp\python-3.13.1-amd64.exe"

Write-Host "Running python-3.13.1-amd64.exe..."
$Proc = Start-Process -FilePath "C:\Temp\python-3.13.1-amd64.exe" `
    -ArgumentList "/quiet", "InstallAllUsers=0", "AppendPath=1", "Include_freethreaded=1" `
    -NoNewWindow `
    -Wait `
    -PassThru

Write-Host "Done."

exit $Proc.ExitCode
