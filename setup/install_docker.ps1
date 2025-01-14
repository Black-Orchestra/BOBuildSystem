New-Item -ItemType Directory -Force -Path "C:\Temp\"

Write-Host "Downloading DockerDesktopInstaller.exe..."
Invoke-WebRequest "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe?utm_source=docker&utm_medium=webreferral&utm_campaign=docs-driven-download-win-amd64" `
    -OutFile "C:\Temp\DockerDesktopInstaller.exe"

Write-Host "Running DockerDesktopInstaller.exe..."
$Proc = Start-Process -FilePath "C:\Temp\DockerDesktopInstaller.exe" `
    -ArgumentList "install", "--quiet" `
    -NoNewWindow `
    -Wait `
    -PassThru

Write-Host "Done."

exit $Proc.ExitCode
