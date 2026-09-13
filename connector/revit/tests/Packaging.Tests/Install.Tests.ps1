#requires -Version 7.4
param([string]$PackageRoot='',[string]$FixtureRoot='',[string]$ChildMode='', [string]$ChildRequest='', [string]$CaseFilter='*')
$ErrorActionPreference='Stop'
$revitRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $revitRoot 'scripts/installation_contract.ps1')
if (-not [string]::IsNullOrEmpty($ChildMode)) {
    $parameters=ConvertFrom-Json -AsHashtable -InputObject ([IO.File]::ReadAllText($ChildRequest))
    if ($ChildMode -ceq 'hold') {
        $originalCopy=(Get-Command Copy-KirInstallPackage).ScriptBlock
        function Copy-KirInstallPackage([string]$Source,[string]$Destination) {
            [Console]::WriteLine('held');[Console]::ReadLine() | Out-Null
            & $originalCopy $Source $Destination
        }
    }
    if ($ChildMode -in @('crash_before','crash_after')) {
        $originalSwitch=(Get-Command Invoke-KirPointerSwitch).ScriptBlock
        function Invoke-KirPointerSwitch([string]$TemporaryPath,[string]$PointerPath,[bool]$HadPrevious,[string]$RemovedBackup) {
            if ($ChildMode -ceq 'crash_after') {& $originalSwitch $TemporaryPath $PointerPath $HadPrevious $RemovedBackup}
            [Console]::WriteLine('crash-point');[Console]::Out.Flush()
            [Diagnostics.Process]::GetCurrentProcess().Kill()
        }
    }
    try {$result=Invoke-KirInstall @parameters;[Console]::WriteLine((ConvertTo-Json -InputObject $result -Depth 8 -Compress));exit 0}
    catch {[Console]::WriteLine((ConvertTo-Json -Compress @{error=$_.Exception.Message}));exit 2}
}
if ([string]::IsNullOrEmpty($FixtureRoot)) {$FixtureRoot=Join-Path ([IO.Path]::GetTempPath()) ('kir-install-tests-'+[Guid]::NewGuid().ToString('N'))}
[IO.Directory]::CreateDirectory($FixtureRoot) | Out-Null
if ([string]::IsNullOrEmpty($PackageRoot)) {
    $buildFixture=Join-Path $FixtureRoot 'build-fixture'
    & (Join-Path $PSScriptRoot 'Run.ps1') -FixtureRoot $buildFixture
    if (-not $?) {throw 'package fixture failed'}
    $PackageRoot=Join-Path $buildFixture 'debug/dist/packages'
}
$packages=@{}
foreach ($year in @('2023','2026')) {
    $directory=Get-ChildItem -LiteralPath (Join-Path $PackageRoot $year) -Directory | Select-Object -First 1
    $packages[$year]=Read-KirPackage $directory.FullName
}
$script:passed=0;$script:failed=0
function Check([bool]$Value,[string]$Message='assertion failed') {if (-not $Value) {throw $Message}}
function Test-Case([string]$Name,[scriptblock]$Body) {
    if ($Name -notlike $CaseFilter) {return}
    try {& $Body;$script:passed++;Write-Host ('PASS '+$Name)}
    catch {$script:failed++;Write-Host ('FAIL '+$Name+': '+$_.Exception.Message);Write-Host $_.ScriptStackTrace}
}
function New-Case([string]$Name,[string]$Year='2023') {
    $root=Join-Path $FixtureRoot $Name
    return @{PackageDirectory=$packages[$Year].Directory;ExpectedPackageId=$packages[$Year].PackageId;RevitVersion=$Year;
        ExpectedActiveManifestSha256='absent';ManifestDirectory=(Join-Path $root 'manifests');ReleaseRoot=(Join-Path $root 'releases');AllowUnverifiedLoad=$true}
}
function Refusal([scriptblock]$Body,[string]$Code) {
    $caught=$null;try {& $Body | Out-Null} catch {$caught=$_}
    Check ($null -ne $caught -and $caught.Exception.Message.Contains($Code)) ('expected '+$Code+', got '+$caught)
    return $caught
}
function Pointer($Options) {return Join-Path $Options.ManifestDirectory $script:KirPointerName}
function BytesHex([string]$Path) {return [Convert]::ToHexString([IO.File]::ReadAllBytes($Path))}
function Rewrite-Intent([string]$Path,[scriptblock]$Change) {
    $data=ConvertFrom-Json -AsHashtable -InputObject ([IO.File]::ReadAllText($Path)); & $Change $data
    $bytes=ConvertTo-KirJsonBytes $data;[IO.File]::WriteAllBytes($Path,$bytes)
    [IO.File]::WriteAllText((Join-Path ([IO.Path]::GetDirectoryName($Path)) 'intent.sha256'),(Get-KirSha $bytes))
}
function Mutated-Package([string]$Name,[scriptblock]$Change) {
    $directory=Join-Path $FixtureRoot ('packages/'+$Name);Copy-KirTree $packages['2023'].Directory $directory;& $Change $directory
    $path=Join-Path $directory 'package.json';$data=ConvertFrom-Json -AsHashtable -InputObject ([IO.File]::ReadAllText($path))
    $data.files=Get-KirInventory $directory -ExcludeManifest;[IO.File]::WriteAllBytes($path,(ConvertTo-KirJsonBytes $data))
    return Read-KirPackage $directory
}
Test-Case 'install inspect and absent rollback preserve releases and recoverable pointer bytes' {
    $options=New-Case 'roundtrip';$result=Invoke-KirInstall @options
    Check ($result.observed.state -ceq 'matches_next' -and -not $result.load_verified -and -not $result.dependency_binding_verified)
    $state=Get-KirInstallationState $result.receipt_path
    Check ($state.switch_attempt_record_complete -and $state.observed.state -ceq 'matches_next' -and -not $state.retry_permitted)
    Check ($state.active_package_state -ceq 'file_set_verified_binding_unverified')
    $before=BytesHex (Pointer $options);$release=Join-Path $options.ReleaseRoot ('2023/'+$options.ExpectedPackageId)
    $inventory=ConvertTo-KirJsonBytes (Get-KirInventory $release)
    $rollback=Invoke-KirRollback $result.receipt_path $result.pointer_sha256 '2023' -AllowUnverifiedLoad
    Check (-not [IO.File]::Exists((Pointer $options)) -and $rollback.pointer_sha256 -ceq 'absent')
    Check ((BytesHex (Join-Path ([IO.Path]::GetDirectoryName($rollback.receipt_path)) 'removed.manifest')) -ceq $before)
    Check ([Convert]::ToHexString((ConvertTo-KirJsonBytes (Get-KirInventory $release))) -ceq [Convert]::ToHexString($inventory))
    Check ((Get-KirInstallationState $rollback.receipt_path).observed.state -ceq 'matches_next')
    Check (@(Get-ChildItem -LiteralPath (Join-Path $options.ManifestDirectory $script:KirLedgerName) -Recurse -File -Filter '*.addin').Count -eq 0)
}
Test-Case 'recognized legacy rollback restores only exact pointer bytes not binaries' {
    $options=New-Case 'legacy';[IO.Directory]::CreateDirectory((Join-Path $options.ManifestDirectory 'KIR.Connector')) | Out-Null
    $legacy=Join-Path $options.ManifestDirectory 'KIR.Connector/Kir.Revit.Connector.dll';[IO.File]::WriteAllText($legacy,'KEEP_LEGACY_BINARY')
    $xml=Read-KirXml (Join-Path $options.PackageDirectory 'Kir.Revit.Connector.addin.template')
    $xml.SelectSingleNode('/RevitAddIns/AddIn/Assembly').InnerText=$legacy;$xml.Save((Pointer $options))
    $before=BytesHex (Pointer $options);$options.ExpectedActiveManifestSha256=(Get-KirPointerBytes (Pointer $options)).Hash
    $result=Invoke-KirInstall @options;Check ($result.previous_pointer_kind -ceq 'legacy_pointer_only')
    $rollback=Invoke-KirRollback $result.receipt_path $result.pointer_sha256 '2023' -AllowUnverifiedLoad
    Check ((BytesHex (Pointer $options)) -ceq $before -and [IO.File]::ReadAllText($legacy) -ceq 'KEEP_LEGACY_BINARY')
    Check ($rollback.binary_restoration -ceq 'not_performed' -and -not $rollback.load_verified)
}
Test-Case 'same-package reactivation has new marker and stale rollback cannot match it' {
    $options=New-Case 'same-package';$first=Invoke-KirInstall @options;$options.ExpectedActiveManifestSha256=$first.pointer_sha256
    $second=Invoke-KirInstall @options;Check ($first.pointer_sha256 -cne $second.pointer_sha256)
    Refusal {Invoke-KirRollback $first.receipt_path $first.pointer_sha256 '2023' -AllowUnverifiedLoad} 'stale_manifest' | Out-Null
    Refusal {Invoke-KirRollback $first.receipt_path $second.pointer_sha256 '2023' -AllowUnverifiedLoad} 'stale_rollback' | Out-Null
    Check ((Get-KirPointerBytes (Pointer $options)).Hash -ceq $second.pointer_sha256)
    $rolled=Invoke-KirRollback $second.receipt_path $second.pointer_sha256 '2023' -AllowUnverifiedLoad
    Check ($rolled.pointer_sha256 -ceq $first.pointer_sha256 -and (Get-KirPointerBytes (Pointer $options)).Hash -ceq $first.pointer_sha256)
}
foreach ($case in @('optin','package','year','stale')) {
    Test-Case ('input refusal '+$case+' precedes filesystem writes') {
        $options=New-Case ('input-'+$case)
        if ($case -ceq 'optin') {$options.AllowUnverifiedLoad=$false;$code='unverified_load_requires_opt_in'}
        elseif ($case -ceq 'package') {$options.ExpectedPackageId='0'*64;$code='unexpected_package'}
        elseif ($case -ceq 'year') {$options.RevitVersion='2026';$code='unexpected_package'}
        else {$options.ExpectedActiveManifestSha256='0'*64;$code='stale_manifest'}
        Refusal {Invoke-KirInstall @options} $code | Out-Null
        Check (-not [IO.Directory]::Exists($options.ManifestDirectory) -and -not [IO.Directory]::Exists($options.ReleaseRoot))
    }
}
foreach ($case in @('malformed','multiple','foreign','path','dtd','marker','empty_name')) {
    Test-Case ('template '+$case+' is rejected before activation') {
        $package=Mutated-Package $case {param($dir)
            $path=Join-Path $dir 'Kir.Revit.Connector.addin.template';$text=[IO.File]::ReadAllText($path)
            switch ($case) {
                malformed {$text='<incomplete'}
                multiple {$text=$text.Replace('</RevitAddIns>',($text.Substring($text.IndexOf('<AddIn Type='),$text.IndexOf('</AddIn>')+8-$text.IndexOf('<AddIn Type='))+'</RevitAddIns>'))}
                foreign {$text=$text.Replace('Kir.Revit.Connector.App','Foreign.Application')}
                path {$text=$text.Replace('>Kir.Revit.Connector.dll<','>/outside.dll<')}
                dtd {
                    $text=$text.Replace('<RevitAddIns>','<!DOCTYPE RevitAddIns [<!ENTITY external SYSTEM "file:///outside">]><RevitAddIns>')
                    # This is valid XML. The unused external entity is never
                    # resolved; only the production DTD prohibition should refuse.
                    $settings=[Xml.XmlReaderSettings]::new()
                    $settings.DtdProcessing=[Xml.DtdProcessing]::Parse;$settings.XmlResolver=$null
                    $inputReader=[IO.StringReader]::new($text)
                    $reader=[Xml.XmlReader]::Create($inputReader,$settings)
                    try {$control=[Xml.XmlDocument]::new();$control.XmlResolver=$null;$control.Load($reader);Check ($control.DocumentElement.LocalName -ceq 'RevitAddIns')}
                    finally {$reader.Dispose();$inputReader.Dispose()}
                }
                marker {$text=$text.Replace('<RevitAddIns>','<!--kir-install/1 operation=00000000-0000-0000-0000-000000000001 package='+('0'*64)+'--><RevitAddIns>')}
                empty_name {$text=$text.Replace('KIR Revit Connector','')}
            }
            [IO.File]::WriteAllText($path,$text)
        }
        $options=New-Case ('template-'+$case);$options.PackageDirectory=$package.Directory;$options.ExpectedPackageId=$package.PackageId
        $caught=$false;try {Invoke-KirInstall @options | Out-Null} catch {$caught=$true}
        Check ($caught -and -not [IO.Directory]::Exists($options.ManifestDirectory) -and -not [IO.Directory]::Exists($options.ReleaseRoot))
    }
}
Test-Case 'foreign current pointer is never adopted even with its exact hash' {
    $options=New-Case 'foreign-pointer';[IO.Directory]::CreateDirectory($options.ManifestDirectory) | Out-Null
    $xml=Read-KirXml (Join-Path $options.PackageDirectory 'Kir.Revit.Connector.addin.template')
    $xml.SelectSingleNode('/RevitAddIns/AddIn/Assembly').InnerText='/outside/other.dll';$xml.Save((Pointer $options))
    $before=BytesHex (Pointer $options);$options.ExpectedActiveManifestSha256=(Get-KirPointerBytes (Pointer $options)).Hash
    Refusal {Invoke-KirInstall @options} 'foreign_pointer_location' | Out-Null
    Check ((BytesHex (Pointer $options)) -ceq $before -and -not [IO.File]::Exists((Join-Path $options.ManifestDirectory $script:KirLeaseName)))
}
Test-Case 'copy failure leaves old pointer and immutable source untouched' {
    $options=New-Case 'copy-fault';$original=(Get-Command Copy-KirInstallPackage).ScriptBlock
    function Copy-KirInstallPackage([string]$Source,[string]$Destination) {
        [IO.Directory]::CreateDirectory($Destination) | Out-Null
        [IO.File]::Copy((Join-Path $Source 'Kir.Revit.Connector.dll'),(Join-Path $Destination 'Kir.Revit.Connector.dll'))
        throw [IO.IOException]::new('injected partial copy failure')
    }
    try {Refusal {Invoke-KirInstall @options} 'partial copy failure' | Out-Null}
    finally {Set-Item Function:Copy-KirInstallPackage $original}
    Check (-not [IO.File]::Exists((Pointer $options)) -and -not [IO.Directory]::Exists((Join-Path $options.ReleaseRoot ('2023/'+$options.ExpectedPackageId))))
    Check ((Read-KirPackage $options.PackageDirectory).PackageId -ceq $options.ExpectedPackageId)
}
Test-Case 'changed copied package identity refuses before switch' {
    $options=New-Case 'copy-mismatch';$original=(Get-Command Copy-KirInstallPackage).ScriptBlock
    function Copy-KirInstallPackage([string]$Source,[string]$Destination) {
        & $original $Source $Destination;[IO.File]::WriteAllText((Join-Path $Destination 'extra.txt'),'changed')
        $path=Join-Path $Destination 'package.json';$data=ConvertFrom-Json -AsHashtable -InputObject ([IO.File]::ReadAllText($path))
        $data.files=Get-KirInventory $Destination -ExcludeManifest;[IO.File]::WriteAllBytes($path,(ConvertTo-KirJsonBytes $data))
    }
    try {Refusal {Invoke-KirInstall @options} 'copied_package_mismatch' | Out-Null}
    finally {Set-Item Function:Copy-KirInstallPackage $original}
    Check (-not [IO.File]::Exists((Pointer $options)))
}
foreach ($case in @('before','after','ack')) {
    Test-Case ('switch fault '+$case+' is observed without automatic rollback') {
        $options=New-Case ('switch-'+$case)
        $originalSwitch=(Get-Command Invoke-KirPointerSwitch).ScriptBlock;$originalAck=(Get-Command Write-KirActivationAcknowledgement).ScriptBlock
        if ($case -ceq 'ack') {
            function Write-KirActivationAcknowledgement([string]$Path,$Observation) {throw [IO.IOException]::new('ack failed')}
        } else {
            function Invoke-KirPointerSwitch([string]$TemporaryPath,[string]$PointerPath,[bool]$HadPrevious,[string]$RemovedBackup) {
                $ledger=Join-Path ([IO.Path]::GetDirectoryName($PointerPath)) $script:KirLedgerName
                $receipt=Get-ChildItem -LiteralPath $ledger -Filter intent.json -Recurse -File | Select-Object -First 1
                Check (Test-KirAttemptMarker (Read-KirInstallIntent $receipt.FullName)) 'attempt marker was not written before native API'
                if ($case -ceq 'after') {& $originalSwitch $TemporaryPath $PointerPath $HadPrevious $RemovedBackup}
                throw [IO.IOException]::new('switch fault')
            }
        }
        try {Refusal {Invoke-KirInstall @options} 'activation_unconfirmed' | Out-Null}
        finally {Set-Item Function:Invoke-KirPointerSwitch $originalSwitch;Set-Item Function:Write-KirActivationAcknowledgement $originalAck}
        $receipt=Get-ChildItem -LiteralPath (Join-Path $options.ManifestDirectory $script:KirLedgerName) -Recurse -Filter intent.json -File | Select-Object -First 1
        $state=Get-KirInstallationState $receipt.FullName
        Check ($state.observed.state -ceq $(if ($case -ceq 'before') {'matches_previous'} else {'matches_next'}))
        Check (-not $state.retry_permitted -and -not $state.load_verified)
    }
}
Test-Case 'rollback removal effect then throw reports absence and keeps backup' {
    $options=New-Case 'rollback-after-effect';$installed=Invoke-KirInstall @options;$original=(Get-Command Invoke-KirPointerSwitch).ScriptBlock
    function Invoke-KirPointerSwitch([string]$TemporaryPath,[string]$PointerPath,[bool]$HadPrevious,[string]$RemovedBackup) {
        & $original $TemporaryPath $PointerPath $HadPrevious $RemovedBackup;throw [IO.IOException]::new('after removal')
    }
    try {Refusal {Invoke-KirRollback $installed.receipt_path $installed.pointer_sha256 '2023' -AllowUnverifiedLoad} 'activation_unconfirmed' | Out-Null}
    finally {Set-Item Function:Invoke-KirPointerSwitch $original}
    Check (-not [IO.File]::Exists((Pointer $options)))
    $record=Get-ChildItem -LiteralPath (Join-Path $options.ManifestDirectory $script:KirLedgerName) -Recurse -Filter intent.json -File |
        Where-Object {(Read-KirInstallIntent $_.FullName).Action -ceq 'rollback'} | Select-Object -First 1
    Check ((Get-KirInstallationState $record.FullName).observed.state -ceq 'matches_next')
    Check ([IO.File]::Exists((Join-Path $record.DirectoryName 'removed.manifest')))
}
foreach ($part in @('intent.sha256','next.manifest','switch-attempted')) {
    Test-Case ('incomplete record '+$part+' never grants replay') {
        $options=New-Case ('incomplete-'+$part);$installed=Invoke-KirInstall @options
        [IO.File]::Delete((Join-Path ([IO.Path]::GetDirectoryName($installed.receipt_path)) $part))
        if ($part -ceq 'switch-attempted') {
            $state=Get-KirInstallationState $installed.receipt_path
            Check ($state.activation_state -ceq 'prepared_or_incomplete_unconfirmed' -and -not $state.retry_permitted)
        } else {$caught=$false;try {Get-KirInstallationState $installed.receipt_path | Out-Null} catch {$caught=$true};Check $caught}
        Check ((Get-KirPointerBytes (Pointer $options)).Hash -ceq $installed.pointer_sha256)
    }
}
foreach ($field in @('next_ref','pointer_path','operation_id','rollback_of')) {
    Test-Case ('tampered receipt '+$field+' cannot redirect restoration') {
        $options=New-Case ('tamper-'+$field);$installed=Invoke-KirInstall @options
        Rewrite-Intent $installed.receipt_path {param($data)
            switch ($field) {next_ref {$data.next_ref='/outside.manifest'} pointer_path {$data.pointer_path='/outside.addin'} operation_id {$data.operation_id=[Guid]::NewGuid().ToString('D')} rollback_of {$data.rollback_of=[Guid]::NewGuid().ToString('D')}}
        }
        $caught=$false;try {Get-KirInstallationState $installed.receipt_path | Out-Null} catch {$caught=$true};Check $caught
        Check ((Get-KirPointerBytes (Pointer $options)).Hash -ceq $installed.pointer_sha256)
    }
}
Test-Case 'read-only inspect of missing receipt creates no directories' {
    $root=Join-Path $FixtureRoot 'missing-inspect';$receipt=Join-Path $root ('.kir-install/'+[Guid]::NewGuid().ToString('D')+'/intent.json')
    Refusal {Get-KirInstallationState $receipt} 'installation_unavailable' | Out-Null;Check (-not [IO.Directory]::Exists($root))
}
Test-Case 'destinations cannot mutate source package or immutable release tree' {
    $options=New-Case 'overlap';$options.ManifestDirectory=$options.PackageDirectory
    Refusal {Invoke-KirInstall @options} 'install_path_overlap' | Out-Null
    $options=New-Case 'overlap2';$options.ManifestDirectory=Join-Path $options.ReleaseRoot '2023/inside'
    Refusal {Invoke-KirInstall @options} 'install_path_overlap' | Out-Null
}
Test-Case 'public false Rollback or Inspect switch never dispatches its selected parameter set' {
    $options=New-Case 'false-action';$installed=Invoke-KirInstall @options
    $front=Join-Path $revitRoot 'scripts/install.ps1'
    Refusal {& $front -Rollback:$false -ReceiptPath $installed.receipt_path -RevitVersion 2023 -ExpectedActiveManifestSha256 $installed.pointer_sha256 -AllowUnverifiedLoad} 'explicit_action_required' | Out-Null
    Refusal {& $front -Inspect:$false -ReceiptPath $installed.receipt_path} 'explicit_action_required' | Out-Null
    Check ((Get-KirPointerBytes (Pointer $options)).Hash -ceq $installed.pointer_sha256)
}
Test-Case 'inspect does not infer complete release files from matching pointer bytes' {
    $options=New-Case 'inspect-package';$installed=Invoke-KirInstall @options
    $file=Join-Path $options.ReleaseRoot ('2023/'+$options.ExpectedPackageId+'/DeclaredAddonDependency.dll')
    [IO.File]::Delete($file)
    $state=Get-KirInstallationState $installed.receipt_path
    Check ($state.observed.state -ceq 'matches_next' -and $state.active_package_state -ceq 'package_unavailable')
    Check (-not $state.load_verified -and -not $state.retry_permitted)
}
Test-Case 'rollback and inspect reject a wrong-year package in a nominal owned container' {
    $options=New-Case 'wrong-year-restore'
    $wrong=$packages['2026'];$wrongDirectory=Join-Path $options.ReleaseRoot ('2023/'+$wrong.PackageId)
    Copy-KirTree $wrong.Directory $wrongDirectory
    [IO.Directory]::CreateDirectory($options.ManifestDirectory) | Out-Null
    $template=[IO.File]::ReadAllBytes((Join-Path $wrong.Directory 'Kir.Revit.Connector.addin.template'))
    $wrongPointer=New-KirManifestBytes $template $wrongDirectory ([Guid]::NewGuid().ToString('D')) $wrong.PackageId
    [IO.File]::WriteAllBytes((Pointer $options),$wrongPointer)
    $options.ExpectedActiveManifestSha256=Get-KirSha $wrongPointer
    # Replacing an explicitly selected broken pointer is not approval to
    # later restore the wrong-year package from its saved bytes.
    $installed=Invoke-KirInstall @options
    Refusal {Invoke-KirRollback $installed.receipt_path $installed.pointer_sha256 '2023' -AllowUnverifiedLoad} 'rollback_package_mismatch' | Out-Null
    Check ((Get-KirPointerBytes (Pointer $options)).Hash -ceq $installed.pointer_sha256)
    [IO.File]::WriteAllBytes((Pointer $options),$wrongPointer)
    $state=Get-KirInstallationState $installed.receipt_path
    Check ($state.observed.state -ceq 'matches_previous' -and $state.active_package_state -ceq 'package_year_mismatch')
}
function Start-Child($Options,[string]$Mode,[string]$Name) {
    $path=Join-Path $FixtureRoot ($Name+'.json');[IO.File]::WriteAllBytes($path,(ConvertTo-KirJsonBytes $Options))
    $start=[Diagnostics.ProcessStartInfo]::new([Environment]::ProcessPath)
    $start.UseShellExecute=$false;$start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    foreach ($value in @('-NoLogo','-NoProfile','-File',$PSCommandPath,'-ChildMode',$Mode,'-ChildRequest',$path)) {$start.ArgumentList.Add($value)}
    return [Diagnostics.Process]::Start($start)
}
function Read-Child($Process) {return $Process.StandardOutput.ReadLineAsync().WaitAsync([TimeSpan]::FromSeconds(20)).GetAwaiter().GetResult()}
function Stop-Child($Process) {if (-not $Process.HasExited) {$Process.Kill();$Process.WaitForExit(10000) | Out-Null};$Process.Dispose()}
Test-Case 'same actual pointer has one lease across year and release-root overrides' {
    $a=New-Case 'same-pointer' '2023';$b=New-Case 'other-release' '2026';$b.ManifestDirectory=$a.ManifestDirectory
    $first=Start-Child $a 'hold' 'first';$second=$null
    try {
        Check ((Read-Child $first) -ceq 'held');$second=Start-Child $b 'install' 'second';$failure=Read-Child $second
        Check ($failure.Contains('installation_busy')) $failure;Check ($second.WaitForExit(10000) -and $second.ExitCode -eq 2)
        $first.StandardInput.WriteLine('continue');$result=ConvertFrom-Json (Read-Child $first)
        Check ($first.WaitForExit(10000) -and $first.ExitCode -eq 0 -and $result.action -ceq 'install');Check (-not [IO.Directory]::Exists($b.ReleaseRoot))
    } finally {Stop-Child $first;if ($null -ne $second) {Stop-Child $second}}
}
Test-Case 'different actual pointers install concurrently without global user lock' {
    $a=New-Case 'independent-a' '2023';$b=New-Case 'independent-b' '2026'
    $first=Start-Child $a 'hold' 'parallel-first';$second=Start-Child $b 'hold' 'parallel-second'
    try {
        Check ((Read-Child $first) -ceq 'held');Check ((Read-Child $second) -ceq 'held')
        $first.StandardInput.WriteLine('continue');$second.StandardInput.WriteLine('continue')
        $one=ConvertFrom-Json (Read-Child $first);$two=ConvertFrom-Json (Read-Child $second)
        Check ($first.WaitForExit(10000) -and $second.WaitForExit(10000) -and $first.ExitCode -eq 0 -and $second.ExitCode -eq 0)
        Check ($one.pointer_path -cne $two.pointer_path -and [IO.File]::Exists((Pointer $a)) -and [IO.File]::Exists((Pointer $b)))
    } finally {Stop-Child $first;Stop-Child $second}
}
foreach ($mode in @('crash_before','crash_after')) {
    Test-Case ('real child '+$mode+' leaves inspectable attempted state without automatic repair') {
        $options=New-Case $mode
        $child=Start-Child $options $mode $mode
        try {Check ((Read-Child $child) -ceq 'crash-point');Check ($child.WaitForExit(10000))}
        finally {Stop-Child $child}
        $receipt=Get-ChildItem -LiteralPath (Join-Path $options.ManifestDirectory $script:KirLedgerName) -Recurse -Filter intent.json -File | Select-Object -First 1
        $state=Get-KirInstallationState $receipt.FullName
        Check ($state.observed.state -ceq $(if ($mode -ceq 'crash_before') {'matches_previous'} else {'matches_next'}))
        Check ($state.switch_attempt_record_complete -and -not $state.retry_permitted)
        Check (-not [IO.File]::Exists((Join-Path $receipt.DirectoryName 'observation.json')))
    }
}
Write-Host "$script:passed passed, $script:failed failed; synthetic per-test destinations only, no real installation/Revit execution"
Write-Host ('Retained fixture: '+$FixtureRoot)
if ($script:failed -gt 0) {exit 1}
