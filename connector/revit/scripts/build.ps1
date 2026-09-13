#requires -Version 7.4
param(
  [ValidateSet('2021','2022','2023','2024','2025','2026')]
  [string[]]$RevitVersion = @('2021','2022','2023','2024','2025','2026'),
  [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
  [string]$OutputRoot = '',
  [ValidateRange(1,9223372036854775807)][long]$MinimumFreeBytes = 6GB,
  [hashtable]$RevitInstallDirs = @{},
  [string]$DotnetPath = 'dotnet'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'package_contract.ps1')
$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrEmpty($OutputRoot)) { $OutputRoot = Join-Path $root 'dist' }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
foreach ($path in @($root,$OutputRoot,$DotnetPath)) { Assert-KirBuildPath $path }
foreach ($capturedRoot in @((Join-Path $root 'src'),(Join-Path $root 'addin'))) {
    $relativeOutput = [IO.Path]::GetRelativePath($capturedRoot,$OutputRoot).Replace('\','/')
    if ($relativeOutput -ceq '.' -or (-not $relativeOutput.StartsWith('../',[StringComparison]::Ordinal) -and -not [IO.Path]::IsPathRooted($relativeOutput))) {
        Stop-KirPackage 'build_output_overlaps_source' 'build output must not enter the captured source tree'
    }
}
if ($RevitVersion.Count -eq 0 -or @($RevitVersion | Select-Object -Unique).Count -ne $RevitVersion.Count) {
    Stop-KirPackage 'build_years_invalid' 'at least one distinct supported year is required'
}
# Operator policy, not a quota or a promise that a later write cannot fail.
# Check before native tools, output creation, and each substantial build phase.
Assert-KirBuildSpace $OutputRoot $MinimumFreeBytes
$resolvedDotnet = (Get-Command $DotnetPath -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
Assert-KirBuildPath $resolvedDotnet
$sdkLines = @(& $resolvedDotnet --version)
if ($LASTEXITCODE -ne 0 -or $sdkLines.Count -ne 1 -or $sdkLines[0] -notmatch '\A8\.\d+\.\d+\z') {
    Stop-KirPackage 'build_sdk_unsupported' 'this packaging profile requires an installed stable .NET8 SDK'
}
$sdk = [string]$sdkLines[0]
$references = @{}
foreach ($year in $RevitVersion) {
    $install = if ($RevitInstallDirs.ContainsKey($year)) { [string]$RevitInstallDirs[$year] } else { "C:\Program Files\Autodesk\Revit $year" }
    Assert-KirBuildPath $install
    $install = (Resolve-Path -LiteralPath $install -ErrorAction Stop).ProviderPath
    Assert-KirBuildPath $install
    foreach ($name in @('RevitAPI.dll','RevitAPIUI.dll')) {
        $path = Join-Path $install $name
        if (-not [IO.File]::Exists($path)) { Stop-KirPackage 'build_reference_missing' ('required reference ' + $name + ' for ' + $year) }
        Assert-KirNotLink $path
        try { $identity = [Reflection.AssemblyName]::GetAssemblyName($path) }
        catch { Stop-KirPackage 'build_reference_invalid' 'reference is not readable managed assembly metadata' }
        if ($identity.Name -cne [IO.Path]::GetFileNameWithoutExtension($name) -or $identity.Version.Major -ne ([int]$year - 2000)) {
            Stop-KirPackage 'build_reference_mismatch' ('reference name/version does not match requested Revit year ' + $year)
        }
    }
    $references[$year] = $install
}
[IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
Assert-KirNotLink $OutputRoot
$stage = Join-Path $OutputRoot ('.staging-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($stage) | Out-Null
# Failure staging is retained for diagnosis. Never recursively clean an output root.
$snapshot = Copy-KirSourceSnapshot $root (Join-Path $stage 'source') $sdk
$source = $snapshot.Root
$props = Read-KirXml (Join-Path $source 'Directory.Build.props')
$versions = @($props.SelectNodes('//*[local-name()="Version"]'))
if ($versions.Count -ne 1 -or [string]::IsNullOrWhiteSpace($versions[0].InnerText)) {
    Stop-KirPackage 'build_version_owner_invalid' 'expected one captured product version'
}
$productVersion = $versions[0].InnerText
$protocolSource = [IO.File]::ReadAllText((Join-Path $source 'src/Kir.Revit.Protocol/Messages.cs'))
$protocolMatches = [regex]::Matches($protocolSource,'public\s+const\s+string\s+Version\s*=\s*"([^"]+)"\s*;')
if ($protocolMatches.Count -ne 1) { Stop-KirPackage 'build_protocol_owner_invalid' 'captured ProtocolConstants version must be one literal' }
$protocol = $protocolMatches[0].Groups[1].Value

function Invoke-KirDotnet([string[]]$Arguments) {
    Assert-KirBuildSpace $OutputRoot $MinimumFreeBytes
    & $resolvedDotnet @Arguments | Out-Host
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { Stop-KirPackage 'build_native_failed' ('dotnet exit ' + $exitCode + '; no package is published') }
}
$common = @(
    "-p:DirectoryBuildPropsPath=$(Join-Path $source 'Directory.Build.props')",
    "-p:DirectoryBuildTargetsPath=$(Join-Path $source 'Directory.Build.targets')",
    "-p:RestoreConfigFile=$(Join-Path $source 'NuGet.Config')",
    "-p:RestorePackagesPath=$(Join-Path $stage 'nuget')",
    "-p:PathMap=$stage=/_/kir-package",
    '-p:EnableSourceControlManagerQueries=false','-p:IncludeSourceRevisionInInformationalVersion=false',
    '-p:NuGetAudit=false','-p:EnableWindowsTargeting=true'
)
# The existing package cache is only a fallback; newly restored dependencies
# live in this task's staging tree. The source config has only official NuGet.
$fallback = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.nuget/packages'
if ([IO.Directory]::Exists($fallback)) { Assert-KirBuildPath $fallback; $common += "-p:RestoreFallbackFolders=$fallback" }

$stagedPackages = [Collections.Generic.List[object]]::new()
Push-Location $source
try {
    foreach ($role in @(@('compiler','Kir.Revit.CompilerHost'),@('client','Kir.Revit.PipeClient'))) {
        $name = $role[1]
        $output = Join-Path $stage ('outputs/' + $role[0])
        $artifacts = Join-Path $stage ('artifacts/' + $role[0])
        Invoke-KirDotnet (@('publish',(Join-Path $source "src/$name/$name.csproj"),'-c',$Configuration,
            '-r','win-x64','--self-contained','true','-p:PublishSingleFile=false','-p:PublishTrimmed=false',
            '--artifacts-path',$artifacts,'-o',$output) + $common)
    }
    foreach ($year in $RevitVersion) {
        $output = Join-Path $stage ('outputs/addin-' + $year)
        $artifacts = Join-Path $stage ('artifacts/addin-' + $year)
        Invoke-KirDotnet (@('build',(Join-Path $source 'src/Kir.Revit.Connector/Kir.Revit.Connector.csproj'),
            '-c',$Configuration,"-p:RevitVersion=$year","-p:RevitInstallDir=$($references[$year])",
            '--artifacts-path',$artifacts,'-o',$output) + $common)
        Assert-KirBuildSpace $OutputRoot $MinimumFreeBytes
        $package = Join-Path $stage ('packages/' + $year)
        Copy-KirTree $output $package
        Copy-KirTree (Join-Path $stage 'outputs/compiler') (Join-Path $package 'compiler')
        Copy-KirTree (Join-Path $stage 'outputs/client') (Join-Path $package 'client')
        [IO.File]::Copy((Join-Path $source 'addin/Kir.Revit.Connector.addin'),(Join-Path $package 'Kir.Revit.Connector.addin.template'),$false)
        $inventory = Get-KirInventory $package
        Assert-KirRoleInventory $inventory
        $manifest = [ordered]@{
            schema=$script:KirPackageSchema;revit_version=$year;configuration=$Configuration;protocol=$protocol
            product_version=$productVersion;sdk_version=$sdk;source_digest=$snapshot.Digest;runtime_identifier='win-x64';files=$inventory
        }
        $bytes = ConvertTo-KirJsonBytes $manifest
        if ($bytes.Length -gt $script:KirPackageMaxManifestBytes) { Stop-KirPackage 'package_manifest_invalid' 'manifest size exceeded' }
        Write-KirNewBytes (Join-Path $package 'package.json') $bytes
        $stagedPackages.Add((Read-KirPackage $package))
    }
    # Builds must not change the captured source/configuration that named them.
    if ((Get-KirSha (ConvertTo-KirJsonBytes (Get-KirInventory $source))) -cne $snapshot.Digest) {
        Stop-KirPackage 'source_snapshot_changed' 'captured source changed during build'
    }
} finally { Pop-Location }

# No final package path is touched until ALL requested builds and validations pass.
# Publication across several years is not a filesystem transaction: a later I/O
# failure can leave earlier COMPLETE packages, never a partly overwritten package.
$published = [Collections.Generic.List[object]]::new()
foreach ($package in $stagedPackages) {
    $parent = Join-Path $OutputRoot ('packages/' + $package.RevitVersion)
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    Assert-KirNotLink $parent
    $destination = Join-Path $parent $package.PackageId
    if ([IO.Directory]::Exists($destination)) {
        $existing = Read-KirPackage $destination
        if ($existing.PackageId -cne $package.PackageId) { Stop-KirPackage 'package_existing_mismatch' 'existing addressed package is not identical' }
    } else { [IO.Directory]::Move($package.Directory,$destination) }
    $published.Add([pscustomobject]@{revit_version=$package.RevitVersion;package_id=$package.PackageId;directory=$destination;
        dependency_binding_verified=$false;load_verified=$false;binding_warnings=$package.BindingWarnings})
}
[pscustomobject]@{schema='kir-revit-build-result/1';packages=@($published);source_digest=$snapshot.Digest;staging_directory=$stage}
