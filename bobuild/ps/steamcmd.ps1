param (
    [Parameter(Mandatory = $True)]
    [String]$SteamCMDExePath,

    [Parameter(Mandatory = $True)]
    [String]$Args
)

$Proc = Start-Process -FilePath "$SteamCMDExePath" `
    -ArgumentList $Args `
    -NoNewWindow `
    -Wait `
    -PassThru

exit $Proc.ExitCode
