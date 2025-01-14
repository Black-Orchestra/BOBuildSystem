param (
    [Parameter(Mandatory = $True)]
    [String]$SteamCMDExePath,

    [Parameter(Mandatory = $True)]
    [String]$Args
)

try
{
    $Proc = Start-Process -FilePath "$SteamCMDExePath" `
        -ArgumentList $Args `
        -NoNewWindow `
        -PassThru

    Wait-Process -Id $Proc.Id
}
finally
{
    $Proc = Get-Process -Id $Proc.Id
    if ($Proc)
    {
        Stop-Process -Id $Proc.Id
    }
}

exit $Proc.ExitCode
