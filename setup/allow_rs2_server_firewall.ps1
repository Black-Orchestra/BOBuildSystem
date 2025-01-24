# TODO: should the ports here be configurable?
# TODO: what happens if the rule exists already?

$ErrorView = 'NormalView'

if (-not $env:BO_RS2_SERVER_INSTALL_DIR)
{
    throw "BO_RS2_SERVER_INSTALL_DIR environment variable is not set!"
}

$RS2Path = "$Env:BO_RS2_SERVER_INSTALL_DIR\Binaries\Win64\VNGame.exe"
$Description = "Rising Storm 2 Dedicated Server networking allowed rule."

$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Outbound UDP" -ErrorAction SilentlyContinue
if (!$Rule)
{
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Outbound UDP" `
        -Direction Outbound -Program $RS2Path `
        -Action Allow -Protocol UDP -Profile Any -Description $Description -Enabled True
}

$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Inbound UDP 7777-7778" -ErrorAction SilentlyContinue
if (!$Rule)
{
    # Game port is 7777, but 7778 is required sometimes too?
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Inbound UDP 7777-7778" `
        -Direction Inbound -Program $RS2Path `
        -Action Allow -Protocol UDP -Profile Any -Description $Description -Enabled True `
        -RemotePort 7777-7778
}

$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Inbound UDP 27015" -ErrorAction SilentlyContinue
if (!$Rule)
{
    # Steam A2S query port.
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Inbound UDP 27015" `
        -Direction Inbound -Program $RS2Path `
        -Action Allow -Protocol UDP -Profile Any -Description $Description -Enabled True `
        -RemotePort 27015
}

$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Outbound TCP" -ErrorAction SilentlyContinue
if (!$Rule)
{
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Outbound TCP" `
        -Direction Outbound -Program $RS2Path `
        -Action Allow -Protocol TCP -Profile Any -Description $Description -Enabled True
}

$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Inbound TCP 8080" -ErrorAction SilentlyContinue
if (!$Rule)
{
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Inbound TCP 8080" `
    -Direction Inbound -Program $RS2Path `
    -Action Allow -Protocol TCP -Profile Any -Description $Description -Enabled True `
    -RemotePort 8080
}

# TODO: for some reason this is also needed. The above rules are not enough?
$Rule = Get-NetFirewallrule -DisplayName "RS2 Dedicated Server Inbound" -ErrorAction SilentlyContinue
if (!$Rule)
{
    New-NetFirewallRule -DisplayName "RS2 Dedicated Server Inbound" `
    -Direction Inbound -Program $RS2Path `
    -Action Allow -Profile Any -Description $Description -Enabled True
}
