$SteamCMDDownloadUrl = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
$SteamCMDDir = "$PSScriptRoot\..\bin\steamcmd"
$SteamCMDZipSavePath = "$SteamCMDDir\steamcmd.zip"
$SteamCMDExePath = "$SteamCMDDir\steamcmd.exe"

# TODO: get BO_STEAMCMD_INSTALL_DIR from env here!

New-Item -ItemType Directory -Force -Path $SteamCMDDir

Write-Host "Downloading SteamCMD to '$SteamCMDZipSavePath'..."
Invoke-WebRequest $SteamCMDDownloadUrl -OutFile $SteamCMDZipSavePath

Write-Host "Extracting '$SteamCMDZipSavePath' to '$SteamCMDDir'..."
Expand-Archive "$SteamCMDZipSavePath" -DestinationPath "$SteamCMDDir" -Force

Write-Host "Running SteamCMD to let it update..."
$Proc = Start-Process -FilePath "$SteamCMDExePath" `
    -ArgumentList "+login anonymous", "+exit" `
    -NoNewWindow `
    -Wait `
    -PassThru

Write-Host "Done."

exit $Proc.ExitCode
