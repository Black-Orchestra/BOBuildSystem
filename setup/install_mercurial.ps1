New-Item -ItemType Directory -Force -Path "C:\Temp\"

Write-Host "Downloading tortoisehg-6.9rc0-x64.msi..."
Invoke-WebRequest "https://www.mercurial-scm.org/release/tortoisehg/windows/tortoisehg-6.9rc0-x64.msi" `
    -OutFile "C:\Temp\tortoisehg-6.9rc0-x64.msi"

Write-Host "Running tortoisehg-6.9rc0-x64.msi..."
$Proc = Start-Process -FilePath "msiexec.exe" `
    -ArgumentList "/I", "C:\Temp\tortoisehg-6.9rc0-x64.msi", "/quiet", "/qn", "/norestart" `
    -NoNewWindow `
    -Wait `
    -PassThru

Write-Host "Done."

exit $Proc.ExitCode
