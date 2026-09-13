#requires -Version 7.4
param([string]$FixtureRoot = '',[string]$DotnetPath = 'dotnet')
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $repoRoot 'scripts/package_contract.ps1')
if ([string]::IsNullOrEmpty($FixtureRoot)) { $FixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('kir-package-tests-' + [Guid]::NewGuid().ToString('N')) }
[IO.Directory]::CreateDirectory($FixtureRoot) | Out-Null
& $DotnetPath build (Join-Path $PSScriptRoot 'FakeDotnet.csproj') -c Release -p:NuGetAudit=false --nologo | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'fake native fixture failed to compile' }
$fake = Join-Path $PSScriptRoot ('bin/Release/net8.0/FakeDotnet' + $(if ($IsWindows) {'.exe'} else {''}))
$refs = @{}
foreach ($year in @('2023','2026')) {
    $refs[$year] = Join-Path $FixtureRoot ('refs/' + $year)
    & $fake --make-refs $refs[$year] $year
    if ($LASTEXITCODE -ne 0) { throw 'fake managed API metadata failed' }
}
$script:passed=0;$script:failed=0
function Check([bool]$Value,[string]$Message='assertion failed') { if (-not $Value) { throw $Message } }
function Test-Case([string]$Name,[scriptblock]$Body) {
    try { & $Body; $script:passed++; Write-Host ('PASS ' + $Name) }
    catch { $script:failed++; Write-Host ('FAIL ' + $Name + ': ' + $_.Exception.Message) }
}
function Put([string]$Path,[string]$Text) {
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path)) | Out-Null
    [IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false))
}
function New-Case([string]$Name) {
    $root = Join-Path $FixtureRoot $Name
    foreach ($relative in @('Directory.Build.props','addin/Kir.Revit.Connector.addin','scripts/build.ps1','scripts/package_contract.ps1')) {
        $destination=Join-Path $root $relative
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
        [IO.File]::Copy((Join-Path $repoRoot $relative),$destination,$false)
    }
    foreach ($project in @('Kir.Revit.Protocol','Kir.Revit.Connector','Kir.Revit.CompilerHost','Kir.Revit.PipeClient')) {
        $source=Join-Path $repoRoot ('src/'+$project)
        foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse -Force) {
            $relative=[IO.Path]::GetRelativePath($source,$file.FullName).Replace('\','/')
            if ($relative -match '(^|/)(bin|obj)/') {continue}
            $destination=Join-Path $root ('src/'+$project+'/'+$relative)
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
            [IO.File]::Copy($file.FullName,$destination,$false)
        }
    }
    return $root
}
function Build-Case([string]$Root,[string]$Mode='success',[string]$Configuration='Release') {
    $env:KIR_PACKAGE_FAKE_MODE=$Mode
    $env:KIR_PACKAGE_FAKE_TRACE=Join-Path $Root 'calls.jsonl'
    return & (Join-Path $Root 'scripts/build.ps1') -RevitVersion @('2023','2026') -Configuration $Configuration `
        -OutputRoot (Join-Path $Root 'dist') -RevitInstallDirs $refs -DotnetPath $fake -MinimumFreeBytes 1
}
function Must-Refuse([scriptblock]$Body,[string]$Code) {
    $caught=$null
    try { & $Body | Out-Null } catch {$caught=$_.Exception.Message}
    Check ($null -ne $caught -and $caught.Contains($Code)) ('expected '+$Code+', got '+$caught)
}
function Rewrite-Manifest([string]$Root,[scriptblock]$Change) {
    $path=Join-Path $Root 'package.json'
    $value=ConvertFrom-Json -AsHashtable -InputObject ([IO.File]::ReadAllText($path))
    & $Change $value
    [IO.File]::WriteAllBytes($path,(ConvertTo-KirJsonBytes $value))
}
function Copy-Package([string]$Root,[string]$Name) {
    $destination=Join-Path $FixtureRoot ('mutations/'+$Name)
    Copy-KirTree $Root $destination
    return $destination
}

$script:good=$null
Test-Case 'Debug packages fresh paired outputs, not stale Release or reused dist' {
    $root=New-Case 'debug'
    Put (Join-Path $root 'src/Kir.Revit.CompilerHost/bin/Release/net8.0/win-x64/publish/Kir.Revit.CompilerHost.exe') 'OLD_HOST_A'
    Put (Join-Path $root 'dist/2023/removed.dll') 'OLD_UNRELATED_OUTPUT'
    $result=Build-Case $root -Configuration Debug
    Check ($result.packages.Count -eq 2)
    foreach ($package in $result.packages) {
        $read=Read-KirPackage $package.directory
        Check ($read.PackageId -ceq $package.package_id)
        Check (-not $read.DependencyBindingVerified -and -not $read.LoadVerified)
        Check ([IO.File]::ReadAllText((Join-Path $package.directory 'compiler/Kir.Revit.CompilerHost.exe')) -ceq 'NEW_Kir.Revit.CompilerHost_Debug')
        Check (-not [IO.File]::Exists((Join-Path $package.directory 'removed.dll')))
        Check ([IO.File]::Exists((Join-Path $package.directory 'compiler/WindowsBase.dll')))
    }
    Check ([IO.File]::ReadAllText((Join-Path $root 'dist/2023/removed.dll')) -ceq 'OLD_UNRELATED_OUTPUT')
    $calls=@(Get-Content -LiteralPath (Join-Path $root 'calls.jsonl') | ForEach-Object {ConvertFrom-Json $_})
    Check ($calls.Count -eq 4)
    $artifactPaths=@($calls | ForEach-Object { $i=[Array]::IndexOf([string[]]$_.args,'--artifacts-path');$_.args[$i+1] })
    Check (@($artifactPaths | Select-Object -Unique).Count -eq 4)
    foreach ($call in $calls) {
        Check ($call.project.StartsWith($result.staging_directory,[StringComparison]::Ordinal))
        Check (@($call.args | Where-Object {$_ -like '-p:DirectoryBuildTargetsPath=*'}).Count -eq 1)
    }
    $script:good=$result.packages[0].directory
}
foreach ($mode in @('publish_fail','client_fail','build_fail_2026','missing_runtime','forbidden_addin','mutate_capture')) {
    Test-Case ('failure '+$mode+' publishes no requested-year package') {
        $root=New-Case $mode
        Put (Join-Path $root 'dist/keep.txt') 'PRESERVE'
        $code=if ($mode -in @('publish_fail','client_fail','build_fail_2026')) {'build_native_failed'} elseif ($mode -eq 'missing_runtime') {'package_runtime_incomplete'} elseif ($mode -eq 'forbidden_addin') {'package_forbidden_dependency'} else {'source_snapshot_changed'}
        Must-Refuse {Build-Case $root $mode} $code
        Check (-not [IO.Directory]::Exists((Join-Path $root 'dist/packages')))
        Check ([IO.File]::ReadAllText((Join-Path $root 'dist/keep.txt')) -ceq 'PRESERVE')
    }
}
Test-Case 'metadata year mismatch refuses before any native component build' {
    $root=New-Case 'wrongyear';$old=$refs['2023'];$refs['2023']=$refs['2026']
    try {Must-Refuse {Build-Case $root} 'build_reference_mismatch'} finally {$refs['2023']=$old}
    Check (-not [IO.File]::Exists((Join-Path $root 'calls.jsonl')))
}
foreach ($form in @('plain','namespaced','attribute','outside_project','external_property','property_function','filesystem_condition')) {
    Test-Case ('unsupported source hook '+$form+' is refused from snapshot') {
        $root=New-Case ('hook_'+$form)
        $project=Join-Path $root 'src/Kir.Revit.PipeClient/Kir.Revit.PipeClient.csproj'
        $text=[IO.File]::ReadAllText($project)
        if ($form -eq 'attribute') {$text=$text.Replace('<Project Sdk="Microsoft.NET.Sdk">','<Project Sdk="Microsoft.NET.Sdk" TreatAsLocalProperty="DirectoryBuildTargetsPath">')}
        elseif ($form -eq 'outside_project') {$text=$text.Replace('../Kir.Revit.Protocol/Kir.Revit.Protocol.csproj','../../../../outside.csproj')}
        elseif ($form -eq 'external_property') {$text=$text.Replace('</Project>','<PropertyGroup><AppConfig>/outside.config</AppConfig></PropertyGroup></Project>')}
        elseif ($form -eq 'property_function') {$text=$text.Replace('</Project>','<PropertyGroup><DefineConstants>$([System.IO.File]::ReadAllText(/outside))</DefineConstants></PropertyGroup></Project>')}
        elseif ($form -eq 'filesystem_condition') {$text=$text.Replace('</Project>','<PropertyGroup Condition="Exists(''/outside'')"><DefineConstants>EXTERNAL</DefineConstants></PropertyGroup></Project>')}
        else {
            if ($form -eq 'namespaced') {$text=$text.Replace('<Project Sdk="Microsoft.NET.Sdk">','<Project Sdk="Microsoft.NET.Sdk" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">')}
            $text=$text.Replace('</Project>','<Import Project="/outside.props" /></Project>')
        }
        Put $project $text
        Must-Refuse {Build-Case $root} $(if ($form -eq 'outside_project') {'source_reference_escape'} else {'source_hook_unsupported'})
        Check (-not [IO.File]::Exists((Join-Path $root 'calls.jsonl')))
    }
}
foreach ($path in @('/tmp/a;Injected=1','/tmp/a%3Bname','/tmp/a,b','/tmp/$name')) {
    Test-Case ('MSBuild metacharacter path is refused: '+$path) {Must-Refuse {Assert-KirBuildPath $path} 'build_path_unsupported'}
}
Test-Case 'output path cannot recursively enter captured project sources' {
    $root=New-Case 'output_overlap'
    Must-Refuse {& (Join-Path $root 'scripts/build.ps1') -RevitVersion 2023 -OutputRoot (Join-Path $root 'src/Kir.Revit.Protocol/output') -DotnetPath $fake -RevitInstallDirs $refs} 'build_output_overlaps_source'
}
Test-Case 'captured XML validation cannot copy a later unvalidated source edit' {
    $root=New-Case 'capture_race';$destination=Join-Path $FixtureRoot 'captured_race'
    $liveProject=Join-Path $root 'src/Kir.Revit.Connector/Kir.Revit.Connector.csproj'
    $capturedProject=Join-Path $destination 'src/Kir.Revit.Connector/Kir.Revit.Connector.csproj'
    $originalReader=${function:Read-KirXml};$script:raceFired=$false
    function Read-KirXml([string]$Path) {
        $value=& $originalReader $Path
        if (($Path -ceq $liveProject -or $Path -ceq $capturedProject) -and -not $script:raceFired) {
            $script:raceFired=$true
            Put $liveProject '<Project Sdk="Microsoft.NET.Sdk"><Import Project="/outside.props" /></Project>'
        }
        return ,$value
    }
    try {
        Copy-KirSourceSnapshot $root $destination '8.0.423' | Out-Null
        Check $script:raceFired
        Check (-not [IO.File]::ReadAllText($capturedProject).Contains('<Import'))
    } finally {${function:Read-KirXml}=$originalReader}
}
Test-Case 'owned captured targets block an actual ancestor MSBuild import' {
    $root=New-Case 'ancestor_root';$parent=Join-Path $FixtureRoot 'ancestor'
    Put (Join-Path $parent 'Directory.Build.targets') '<Project><PropertyGroup><KIR_UNCAPTURED_IMPORT>outside</KIR_UNCAPTURED_IMPORT></PropertyGroup></Project>'
    $destination=Join-Path $parent 'captured'
    Copy-KirSourceSnapshot $root $destination '8.0.423' | Out-Null
    Push-Location $destination
    try {
        $value=@(& $DotnetPath msbuild (Join-Path $destination 'src/Kir.Revit.PipeClient/Kir.Revit.PipeClient.csproj') -nologo -getProperty:KIR_UNCAPTURED_IMPORT)
        Check ($LASTEXITCODE -eq 0 -and [string]::IsNullOrWhiteSpace(($value -join '')))
    } finally {Pop-Location}
}
if ($null -ne $script:good) {
    Test-Case 'identical addressed packages are verified and never overwritten' {
        $root=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $script:good)))
        $before=[IO.File]::ReadAllBytes((Join-Path $script:good 'package.json'))
        $again=Build-Case $root -Configuration Debug
        Check ($again.packages[0].directory -ceq $script:good)
        Check ([Convert]::ToHexString([IO.File]::ReadAllBytes((Join-Path $script:good 'package.json'))) -ceq [Convert]::ToHexString($before))
    }
    Test-Case 'manifest bytes have no culture-sensitive false BOM refusal' {Read-KirPackage $script:good | Out-Null}
    foreach ($mutation in @('extra','missing','tampered','duplicate','casecollision','traversal','device','ads','empty_deps','missing_asset','framework_dependent','missing_addin_dependency','wrong_addin_identity','symlink')) {
        Test-Case ('package refuses '+$mutation) {
            $copy=Copy-Package $script:good $mutation
            if ($mutation -eq 'extra') {Put (Join-Path $copy 'extra.dll') 'EXTRA'}
            elseif ($mutation -eq 'missing') {[IO.File]::Delete((Join-Path $copy 'Kir.Revit.Connector.dll'))}
            elseif ($mutation -eq 'tampered') {Put (Join-Path $copy 'Kir.Revit.Connector.dll') 'MODIFIED'}
            elseif ($mutation -eq 'duplicate') { $p=Join-Path $copy 'package.json';$s=[IO.File]::ReadAllText($p);Put $p ($s.Replace('"schema":','"schema":"kir-revit-package/1","schema":')) }
            elseif ($mutation -eq 'symlink') {New-Item -ItemType SymbolicLink -Path (Join-Path $copy 'linked.dll') -Target (Join-Path $copy 'Kir.Revit.Protocol.dll') | Out-Null}
            elseif ($mutation -in @('casecollision','traversal','device','ads')) {
                Rewrite-Manifest $copy {param($m)
                    if ($mutation -eq 'casecollision') {$m.files+=@{path=$m.files[0].path.ToUpperInvariant();size=0;sha256=('0'*64)}}
                    else {$m.files[0].path=switch($mutation){traversal{'../escape'} device{'CON.txt'} ads{'test:stream'}}}
                }
            } else {
                if ($mutation -eq 'missing_addin_dependency') {[IO.File]::Delete((Join-Path $copy 'DeclaredAddonDependency.dll'))}
                elseif ($mutation -eq 'wrong_addin_identity') {[IO.File]::Copy((Join-Path $copy 'Kir.Revit.Protocol.dll'),(Join-Path $copy 'DeclaredAddonDependency.dll'),$true)}
                elseif ($mutation -eq 'empty_deps') {Put (Join-Path $copy 'client/Kir.Revit.PipeClient.deps.json') '{"runtimeTarget":{"name":".NETCoreApp,Version=v8.0/win-x64"},"targets":{".NETCoreApp,Version=v8.0/win-x64":{}}}'}
                elseif ($mutation -eq 'missing_asset') {[IO.File]::Delete((Join-Path $copy 'client/DeclaredDependency.dll'))}
                else {Put (Join-Path $copy 'client/Kir.Revit.PipeClient.runtimeconfig.json') '{"runtimeOptions":{"tfm":"net8.0","framework":{"name":"Microsoft.NETCore.App","version":"8.0.29"}}}'}
                Rewrite-Manifest $copy {param($m) $m.files=Get-KirInventory $copy -ExcludeManifest}
            }
            $caught=$false;try {Read-KirPackage $copy | Out-Null} catch {$caught=$true}
            Check $caught ('accepted mutation '+$mutation)
        }
    }
}
Write-Host "$script:passed passed, $script:failed failed; synthetic native build outputs, real managed metadata, no install/Revit execution"
Write-Host ('Retained fixture: '+$FixtureRoot)
if ($script:failed -gt 0) {exit 1}
