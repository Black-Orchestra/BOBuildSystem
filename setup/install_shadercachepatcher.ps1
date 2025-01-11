$OutFile = "$PSScriptRoot/../bin/UE3ShaderCachePatcherCLI.exe"

Write-Host "Downloading UE3ShaderCachePatcherCLI.exe..."
Invoke-WebRequest "https://github.com/tuokri/UE3ShaderCachePatcher/releases/download/1.1.0/UE3ShaderCachePatcherCLI.exe" `
    -OutFile $OutFile
