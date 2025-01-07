# TODO: is 2012 the correct version for RS2?

$ErrorView = 'NormalView'

New-Item "C:\Temp\" -ItemType Directory -ErrorAction SilentlyContinue

Install-Module -Name VcRedist -Force
New-Item -Path C:\Temp\VcRedist -ItemType Directory -Force
$VcList = Get-VcList -Export Unsupported | Where-Object { $_.Release -eq "2012" }
$VcList = Save-VcRedist -VcList $VcList -Path C:\Temp\VcRedist
Install-VcRedist -VcList $VcList -Silent

Exit $LASTEXITCODE
