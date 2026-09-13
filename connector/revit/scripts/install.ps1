#requires -Version 7.4
[CmdletBinding(DefaultParameterSetName='Install')]
param(
    [Parameter(Mandatory,ParameterSetName='Install')][string]$PackageDirectory,
    [Parameter(Mandatory,ParameterSetName='Install')][string]$ExpectedPackageId,
    [Parameter(Mandatory,ParameterSetName='Install')][Parameter(Mandatory,ParameterSetName='Rollback')]
    [ValidateSet('2021','2022','2023','2024','2025','2026')][string]$RevitVersion,
    [Parameter(Mandatory,ParameterSetName='Install')][Parameter(Mandatory,ParameterSetName='Rollback')]
    [string]$ExpectedActiveManifestSha256,
    [Parameter(ParameterSetName='Install')][string]$ManifestDirectory='',
    [Parameter(ParameterSetName='Install')][string]$ReleaseRoot='',
    [Parameter(ParameterSetName='Install')][Parameter(ParameterSetName='Rollback')][switch]$AllowUnverifiedLoad,
    [Parameter(Mandatory,ParameterSetName='Inspect')][switch]$Inspect,
    [Parameter(Mandatory,ParameterSetName='Rollback')][switch]$Rollback,
    [Parameter(Mandatory,ParameterSetName='Inspect')][Parameter(Mandatory,ParameterSetName='Rollback')][string]$ReceiptPath
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'installation_contract.ps1')
switch ($PSCmdlet.ParameterSetName) {
    'Inspect' {
        if (-not $Inspect.IsPresent) {Stop-KirInstall 'explicit_action_required' 'Inspect switch must be explicitly true'}
        Get-KirInstallationState -ReceiptPath $ReceiptPath
    }
    'Rollback' {
        if (-not $Rollback.IsPresent) {Stop-KirInstall 'explicit_action_required' 'Rollback switch must be explicitly true'}
        Invoke-KirRollback -ReceiptPath $ReceiptPath -ExpectedActiveManifestSha256 $ExpectedActiveManifestSha256 -RevitVersion $RevitVersion -AllowUnverifiedLoad:$AllowUnverifiedLoad
    }
    'Install' {
        if ([string]::IsNullOrEmpty($ManifestDirectory)) {
            if ([string]::IsNullOrWhiteSpace($env:APPDATA)) {Stop-KirInstall 'install_root_required' 'APPDATA is unavailable; choose an explicit manifest directory'}
            $ManifestDirectory=Join-Path $env:APPDATA ('Autodesk/Revit/Addins/'+$RevitVersion)
        }
        if ([string]::IsNullOrEmpty($ReleaseRoot)) {
            if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {Stop-KirInstall 'install_root_required' 'LOCALAPPDATA is unavailable; choose an explicit release root'}
            $ReleaseRoot=Join-Path $env:LOCALAPPDATA 'KIR/connector/releases'
        }
        $options=@{PackageDirectory=$PackageDirectory;ExpectedPackageId=$ExpectedPackageId;RevitVersion=$RevitVersion;
            ExpectedActiveManifestSha256=$ExpectedActiveManifestSha256;ManifestDirectory=$ManifestDirectory;
            ReleaseRoot=$ReleaseRoot;AllowUnverifiedLoad=$AllowUnverifiedLoad}
        Invoke-KirInstall @options
    }
}
