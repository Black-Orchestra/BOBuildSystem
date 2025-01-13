$OutFile = "$PSScriptRoot/../bin/steamguard.exe"

Write-Host "Downloading steamguard.exe..."
Invoke-WebRequest "https://github.com/dyc3/steamguard-cli/releases/download/v0.15.0/steamguard.exe" `
    -OutFile $OutFile

Exit $LASTEXITCODE
