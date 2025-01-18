$OutFile = "$PSScriptRoot/../bin/UE3PackageTool.exe"

Write-Host "Downloading UE3PackageTool.exe..."
Invoke-WebRequest "https://github.com/tuokri/UE3PackageTool/releases/download/0.1.0/UE3PackageTool.exe" `
    -OutFile $OutFile

Exit $LASTEXITCODE
