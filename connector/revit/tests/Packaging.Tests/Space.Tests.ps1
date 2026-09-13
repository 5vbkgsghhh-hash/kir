#requires -Version 7.4
# No fixture directories, builds, package copies, or cleanup.
$ErrorActionPreference='Stop'
$connectorRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $connectorRoot 'scripts/package_contract.ps1')
$spaceProbe=Join-Path $connectorRoot ('dist/space-check-'+[Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $spaceProbe) {throw 'probe unexpectedly exists'}
$observed=Get-KirAvailableBuildBytes $spaceProbe
if ($observed -lt 0) {throw 'negative available space'}
$originalSpaceReader=(Get-Command Get-KirAvailableBuildBytes).ScriptBlock
try {
    function Get-KirAvailableBuildBytes([string]$Path) {return 99L}
    $refused=$false
    try {Assert-KirBuildSpace $spaceProbe 100}
    catch {$refused=$_.Exception.Message.StartsWith('build_space_insufficient:')}
    if (-not $refused) {throw 'insufficient space was accepted'}
    Assert-KirBuildSpace $spaceProbe 99
    $refused=$false
    try {Assert-KirBuildSpace $spaceProbe 0}
    catch {$refused=$_.Exception.Message.StartsWith('build_space_policy_invalid:')}
    if (-not $refused) {throw 'invalid zero policy was accepted'}
} finally {Set-Item Function:Get-KirAvailableBuildBytes $originalSpaceReader}

# The real entrypoint must refuse before even resolving this nonexistent tool.
$refused=$false
try {
    & (Join-Path $connectorRoot 'scripts/build.ps1') -RevitVersion 2023 -OutputRoot $spaceProbe `
        -MinimumFreeBytes 9223372036854775807 -DotnetPath (Join-Path $connectorRoot 'definitely-not-a-dotnet-tool') | Out-Null
} catch {$refused=$_.Exception.Message.StartsWith('build_space_insufficient:')}
if (-not $refused) {throw 'build entrypoint did not refuse at the space boundary'}
if (Test-Path -LiteralPath $spaceProbe) {throw 'space check created output'}
Write-Host 'PASS low-space refusal, equality boundary, invalid policy, and real pre-tool/pre-directory build refusal; no artifacts created'
