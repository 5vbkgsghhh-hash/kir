#requires -Version 7.4
# Pointer activation only. Never load an assembly, restart Revit or edit its config.
. (Join-Path $PSScriptRoot 'package_contract.ps1')
$script:KirIntentSchema='kir-revit-install-intent/1'
$script:KirPointerName='Kir.Revit.Connector.addin'
$script:KirLeaseName='.Kir.Revit.Connector.install.lock'
$script:KirLedgerName='.kir-install'
$script:KirAddinId='4fbaa279-5b36-4553-a9db-74a6ef28bb11'

function Get-KirReceiptLocation([string]$ReceiptPath) {
    $path=Get-KirInstallPath $ReceiptPath
    if ([IO.Path]::GetFileName($path) -cne 'intent.json') {Stop-KirInstall 'invalid_receipt_path' 'expected intent.json'}
    $operationDirectory=[IO.Path]::GetDirectoryName($path)
    Get-KirOperationId ([IO.Path]::GetFileName($operationDirectory)) | Out-Null
    $ledger=[IO.Path]::GetDirectoryName($operationDirectory)
    if ([IO.Path]::GetFileName($ledger) -cne $script:KirLedgerName) {Stop-KirInstall 'invalid_receipt_path' 'receipt is outside the activation ledger'}
    return [IO.Path]::GetDirectoryName($ledger)
}
function Test-KirAttemptMarker($Intent) {
    $path=Join-Path $Intent.Directory 'switch-attempted'
    if (-not [IO.File]::Exists($path)) {return $false}
    $bytes=Read-KirInstallBytes $path 128
    return [Text.Encoding]::ASCII.GetString($bytes) -ceq ('kir-pointer-switch/1 '+$Intent.OperationId)
}
function Get-KirInstallationState([string]$ReceiptPath) {
    $directory=Get-KirReceiptLocation $ReceiptPath
    $lease=Open-KirInstallLease $directory -ExistingOnly
    try {
        $intent=Read-KirInstallIntent $ReceiptPath
        $observation=Get-KirInstallObservation $intent.Pointer $intent.Previous.Hash $intent.Next.Hash
        $attempt=Test-KirAttemptMarker $intent
        $active=Get-KirActivePackageState $intent $observation.sha256
        return [pscustomobject]@{schema='kir-install-observation/1';operation_id=$intent.OperationId;receipt_path=$intent.Path;
            action=$intent.Action;pointer_path=$intent.Pointer;switch_attempt_record_complete=$attempt;observed=$observation;
            activation_state=$(if ($attempt) {'observed_not_loader_verified'} else {'prepared_or_incomplete_unconfirmed'});
            active_package_state=$active.state;active_package_id=$active.package_id;binding_warnings=$active.binding_warnings;
            retry_permitted=$false;load_verified=$false;dependency_binding_verified=$false}
    } finally {$lease.Dispose()}
}
function Get-KirActivePackageState($Intent,[string]$ObservedHash) {
    if ([string]::IsNullOrEmpty($ObservedHash)) {return [pscustomobject]@{state='pointer_unavailable';package_id=$null;binding_warnings=@()}}
    try {$current=Assert-KirCurrentHash $Intent.Pointer $ObservedHash}
    catch {return [pscustomobject]@{state='pointer_changed_or_unavailable';package_id=$null;binding_warnings=@()}}
    if ($null -eq $current.Bytes) {return [pscustomobject]@{state='no_active_pointer';package_id=$null;binding_warnings=@()}}
    try {$owned=Get-KirOwnedManifest $current.Bytes $Intent.Pointer $Intent.ReleaseRoot $Intent.Year}
    catch {return [pscustomobject]@{state='pointer_unrecognized';package_id=$null;binding_warnings=@()}}
    if ($owned.Kind -ceq 'legacy_pointer_only') {return [pscustomobject]@{state='legacy_pointer_only';package_id=$null;binding_warnings=@([pscustomobject]@{status='legacy_binaries_not_verified'})}}
    try {
        $package=Read-KirPackage (Join-Path $Intent.ReleaseRoot ($Intent.Year+'/'+$owned.PackageId))
        if ($package.PackageId -cne $owned.PackageId) {throw 'identity mismatch'}
        if ($package.RevitVersion -cne $Intent.Year) {return [pscustomobject]@{state='package_year_mismatch';package_id=$owned.PackageId;binding_warnings=@()}}
        return [pscustomobject]@{state='file_set_verified_binding_unverified';package_id=$owned.PackageId;binding_warnings=$package.BindingWarnings}
    } catch {return [pscustomobject]@{state='package_unavailable';package_id=$owned.PackageId;binding_warnings=@()}}
}

# Tiny failure-injection seams: tests invoke the real API and can then throw.
function Invoke-KirPointerSwitch([string]$TemporaryPath,[string]$PointerPath,[bool]$HadPrevious,[string]$RemovedBackup) {
    if ([string]::IsNullOrEmpty($TemporaryPath)) {[IO.File]::Move($PointerPath,$RemovedBackup)}
    elseif ($HadPrevious) {
        if (Test-Path -LiteralPath $RemovedBackup) {Stop-KirInstall 'backup_path_exists' 'native replacement backup already exists'}
        # PowerShell converts $null for this overload into an empty string.
        # Use our fixed non-scanned backup path, not an ambiguous null argument.
        [IO.File]::Replace($TemporaryPath,$PointerPath,$RemovedBackup)
    }
    else {[IO.File]::Move($TemporaryPath,$PointerPath)}
}
function Write-KirActivationAcknowledgement([string]$Path,$Observation) {Write-KirNewBytes $Path (ConvertTo-KirJsonBytes $Observation)}
function Copy-KirInstallPackage([string]$Source,[string]$Destination) {Copy-KirTree $Source $Destination}

function Complete-KirPointerAction($Data,[byte[]]$Previous,[byte[]]$Next,$BindingWarnings) {
    $manifestDirectory=[IO.Path]::GetDirectoryName($Data.pointer_path)
    $receipt=New-KirInstallIntent $manifestDirectory $Data $Previous $Next
    $intent=Read-KirInstallIntent $receipt
    $temporary=$null
    if ($null -ne $Next) {
        $temporary=Join-Path $manifestDirectory ('.Kir.Revit.Connector.'+$Data.operation_id+'.pending')
        Write-KirNewBytes $temporary $Next
    }
    Assert-KirCurrentHash $Data.pointer_path $Data.previous_sha256 | Out-Null
    $attempted=$false
    try {
        $attempted=$true # An exception may occur AFTER the physical effect.
        Write-KirNewBytes (Join-Path $intent.Directory 'switch-attempted') ([Text.Encoding]::ASCII.GetBytes(('kir-pointer-switch/1 '+$Data.operation_id)))
        Invoke-KirPointerSwitch $temporary $Data.pointer_path ($Data.previous_sha256 -cne 'absent') (Join-Path $intent.Directory 'removed.manifest')
        $observation=Get-KirInstallObservation $Data.pointer_path $Data.previous_sha256 $Data.next_sha256
        if ($observation.state -cne 'matches_next') {Stop-KirInstall 'pointer_readback_mismatch' 'pointer did not match desired bytes after switch'}
        $result=[pscustomobject]@{schema='kir-install-result/1';action=$Data.action;operation_id=$Data.operation_id;receipt_path=$receipt;
            pointer_path=$Data.pointer_path;pointer_sha256=$Data.next_sha256;package_id=$Data.package_id;observed=$observation;
            activation_state='pointer_switched_not_loader_verified';previous_pointer_kind=$Data.previous_kind;
            retry_permitted=$false;dependency_binding_verified=$false;load_verified=$false;binding_warnings=@($BindingWarnings);
            binary_restoration='not_performed';durability_scope='flushed_file_contents_and_observed_ordering_not_power_loss_proof'}
        Write-KirActivationAcknowledgement (Join-Path $intent.Directory 'observation.json') $result
        return $result
    } catch {
        if ($attempted) {
            $state=[pscustomobject]@{schema='kir-install-observation/1';operation_id=$Data.operation_id;receipt_path=$receipt;
                pointer_path=$Data.pointer_path;observed=(Get-KirInstallObservation $Data.pointer_path $Data.previous_sha256 $Data.next_sha256);
                activation_state='activation_unconfirmed';retry_permitted=$false;load_verified=$false;dependency_binding_verified=$false}
            Stop-KirInstall 'activation_unconfirmed' ('switch/acknowledgement failed; inspect '+$receipt+'; no automatic rollback') $state
        }
        throw
    }
}


function Invoke-KirInstall([string]$PackageDirectory,[string]$ExpectedPackageId,[string]$RevitVersion,
    [string]$ExpectedActiveManifestSha256,[string]$ManifestDirectory,[string]$ReleaseRoot,[switch]$AllowUnverifiedLoad) {
    if ($RevitVersion -cnotin @('2021','2022','2023','2024','2025','2026')) {Stop-KirInstall 'invalid_install_year' 'unsupported Revit year'}
    $expectedPackage=Get-KirExpectedHash $ExpectedPackageId
    $expectedPointer=Get-KirExpectedHash $ExpectedActiveManifestSha256 -AllowAbsent
    $source=Get-KirInstallPath $PackageDirectory;$manifestDirectory=Get-KirInstallPath $ManifestDirectory;$releaseRoot=Get-KirInstallPath $ReleaseRoot
    foreach ($path in @($source,$manifestDirectory,$releaseRoot)) {Assert-KirInstallAncestors $path}
    foreach ($destination in @($manifestDirectory,$releaseRoot)) {
        if (Test-KirInstallInside $destination $source) {Stop-KirInstall 'install_path_overlap' 'installation cannot write inside its input package'}
    }
    if (Test-KirInstallInside $manifestDirectory $releaseRoot) {Stop-KirInstall 'install_path_overlap' 'active pointer cannot be inside immutable release storage'}
    $package=Read-KirPackage $source
    if ($package.PackageId -cne $expectedPackage -or $package.RevitVersion -cne $RevitVersion) {Stop-KirInstall 'unexpected_package' 'package identity/year differs from the explicit request'}
    if (-not $AllowUnverifiedLoad -and (-not $package.LoadVerified -or -not $package.DependencyBindingVerified)) {Stop-KirInstall 'unverified_load_requires_opt_in' 'explicit controlled-pilot opt-in is required'}
    $template=Read-KirPackageTemplate $package
    $pointer=Join-Path $manifestDirectory $script:KirPointerName
    $previous=Assert-KirCurrentHash $pointer $expectedPointer
    Get-KirOwnedManifest $previous.Bytes $pointer $releaseRoot $RevitVersion | Out-Null
    $lease=Open-KirInstallLease $manifestDirectory
    try {
        $previous=Assert-KirCurrentHash $pointer $expectedPointer
        $old=Get-KirOwnedManifest $previous.Bytes $pointer $releaseRoot $RevitVersion
        $releaseDirectory=Join-Path $releaseRoot ($RevitVersion+'/'+$expectedPackage)
        Assert-KirInstallAncestors $releaseDirectory
        if ([IO.Directory]::Exists($releaseDirectory)) {
            $existing=Read-KirPackage $releaseDirectory
            if ($existing.PackageId -cne $expectedPackage -or $existing.RevitVersion -cne $RevitVersion) {Stop-KirInstall 'existing_release_mismatch' 'addressed release is not the exact package'}
        } else {
            $parent=[IO.Path]::GetDirectoryName($releaseDirectory);[IO.Directory]::CreateDirectory($parent) | Out-Null
            $stage=Join-Path $parent ('.staging-'+[Guid]::NewGuid().ToString('N'))
            Copy-KirInstallPackage $source $stage
            $copied=Read-KirPackage $stage
            if ($copied.PackageId -cne $expectedPackage -or $copied.RevitVersion -cne $RevitVersion) {Stop-KirInstall 'copied_package_mismatch' 'copied package identity differs'}
            try {[IO.Directory]::Move($stage,$releaseDirectory)}
            catch {
                if (-not [IO.Directory]::Exists($releaseDirectory)) {throw}
                $raced=Read-KirPackage $releaseDirectory
                if ($raced.PackageId -cne $expectedPackage) {Stop-KirInstall 'existing_release_mismatch' 'concurrent release differs'}
            }
        }
        $installed=Read-KirPackage $releaseDirectory
        if ($installed.PackageId -cne $expectedPackage) {Stop-KirInstall 'existing_release_mismatch' 'installed release changed'}
        $template=Read-KirPackageTemplate $installed
        $operation=[Guid]::NewGuid().ToString('D')
        $next=New-KirManifestBytes $template $releaseDirectory $operation $expectedPackage
        $data=[ordered]@{schema=$script:KirIntentSchema;operation_id=$operation;action='install';revit_version=$RevitVersion;
            pointer_path=$pointer;release_root=$releaseRoot;package_id=$expectedPackage;previous_sha256=$previous.Hash;next_sha256=(Get-KirSha $next);
            previous_ref=$(if ($null -eq $previous.Bytes) {$null} else {'previous.manifest'});next_ref='next.manifest';previous_kind=$old.Kind;
            rollback_of=$null;load_verified=$false;dependency_binding_verified=$false}
        return Complete-KirPointerAction $data $previous.Bytes $next $installed.BindingWarnings
    } finally {$lease.Dispose()}
}

function Invoke-KirRollback([string]$ReceiptPath,[string]$ExpectedActiveManifestSha256,[string]$RevitVersion,[switch]$AllowUnverifiedLoad) {
    $expected=Get-KirExpectedHash $ExpectedActiveManifestSha256 -AllowAbsent
    $manifestDirectory=Get-KirReceiptLocation $ReceiptPath
    $lease=Open-KirInstallLease $manifestDirectory -ExistingOnly
    try {
        $source=Read-KirInstallIntent $ReceiptPath
        if ($source.Action -cne 'install' -or $source.Year -cne $RevitVersion -or -not (Test-KirAttemptMarker $source)) {Stop-KirInstall 'rollback_source_invalid' 'expected a complete attempted installation record for this year'}
        if ($expected -cne $source.Next.Hash) {Stop-KirInstall 'stale_rollback' 'explicit current hash must identify this installation pointer'}
        $current=Assert-KirCurrentHash $source.Pointer $expected
        if (-not $AllowUnverifiedLoad) {Stop-KirInstall 'unverified_load_requires_opt_in' 'rollback does not prove old binaries or loader state'}
        $old=Get-KirOwnedManifest $source.Previous.Bytes $source.Pointer $source.ReleaseRoot $source.Year
        $warnings=@()
        if ($old.Kind -ceq 'managed_release') {
            $package=Read-KirPackage (Join-Path $source.ReleaseRoot ($source.Year+'/'+$old.PackageId))
            if ($package.PackageId -cne $old.PackageId -or $package.RevitVersion -cne $source.Year) {Stop-KirInstall 'rollback_package_mismatch' 'old release identity/year does not match its pointer'}
            $warnings=$package.BindingWarnings
        } elseif ($old.Kind -ceq 'legacy_pointer_only') {$warnings=@([pscustomobject]@{status='legacy_pointer_only';binary_restoration='not_performed'})}
        $operation=[Guid]::NewGuid().ToString('D')
        $data=[ordered]@{schema=$script:KirIntentSchema;operation_id=$operation;action='rollback';revit_version=$source.Year;
            pointer_path=$source.Pointer;release_root=$source.ReleaseRoot;package_id=$source.PackageId;previous_sha256=$current.Hash;next_sha256=$source.Previous.Hash;
            previous_ref='previous.manifest';next_ref=$(if ($null -eq $source.Previous.Bytes) {$null} else {'next.manifest'});previous_kind='managed_release';
            rollback_of=$source.OperationId;load_verified=$false;dependency_binding_verified=$false}
        return Complete-KirPointerAction $data $current.Bytes $source.Previous.Bytes $warnings
    } finally {$lease.Dispose()}
}


function Stop-KirInstall([string]$Code,[string]$Message,$State=$null) {
    $exception=[InvalidOperationException]::new($Code+': '+$Message)
    $exception.Data['code']=$Code
    if ($null -ne $State) {$exception.Data['installation_state']=$State}
    throw $exception
}
function Get-KirInstallPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or -not [IO.Path]::IsPathFullyQualified($Path) -or @($Path.ToCharArray() | Where-Object {[char]::IsControl($_)}).Count -gt 0) {
        Stop-KirInstall 'invalid_install_path' 'expected an absolute filesystem path without control characters'
    }
    return [IO.Path]::TrimEndingDirectorySeparator([IO.Path]::GetFullPath($Path))
}
function Test-KirSamePath([string]$A,[string]$B) {
    $comparison=if ($IsWindows) {[StringComparison]::OrdinalIgnoreCase} else {[StringComparison]::Ordinal}
    return [string]::Equals((Get-KirInstallPath $A),(Get-KirInstallPath $B),$comparison)
}
function Test-KirInstallInside([string]$Child,[string]$Parent) {
    $relative=[IO.Path]::GetRelativePath((Get-KirInstallPath $Parent),(Get-KirInstallPath $Child)).Replace('\','/')
    return $relative -ceq '.' -or ($relative -cne '..' -and -not $relative.StartsWith('../',[StringComparison]::Ordinal) -and -not [IO.Path]::IsPathRooted($relative))
}
function Assert-KirInstallAncestors([string]$Path) {
    $current=[IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrEmpty($current)) {
        if (Test-Path -LiteralPath $current) {Assert-KirNotLink $current}
        $parent=[IO.Path]::GetDirectoryName($current)
        if ($parent -ceq $current) {break}
        $current=$parent
    }
}
function Get-KirExpectedHash([string]$Value,[switch]$AllowAbsent) {
    if ($AllowAbsent -and $Value -ceq 'absent') {return 'absent'}
    if ($Value -notmatch '\A[0-9a-fA-F]{64}\z') {Stop-KirInstall 'invalid_expected_hash' 'expected SHA-256 or explicit absent sentinel'}
    return $Value.ToLowerInvariant()
}
function Get-KirOperationId([string]$Value) {
    $id=[Guid]::Empty
    if (-not [Guid]::TryParse($Value,[ref]$id) -or $id -eq [Guid]::Empty -or $id.ToString('D') -cne $Value) {
        Stop-KirInstall 'invalid_receipt' 'operation id must be canonical and nonempty'
    }
    return $Value
}
function Read-KirInstallBytes([string]$Path,[int]$Limit) {
    Assert-KirInstallAncestors $Path
    $stream=[IO.File]::OpenRead($Path)
    try {
        $buffer=[byte[]]::new($Limit+1);$offset=0
        while ($offset -lt $buffer.Length) {$read=$stream.Read($buffer,$offset,$buffer.Length-$offset);if ($read -eq 0) {break};$offset+=$read}
        if ($offset -gt $Limit) {Stop-KirInstall 'install_record_budget' 'bounded installation file is too large'}
        $bytes=[byte[]]::new($offset);[Array]::Copy($buffer,$bytes,$offset);return ,$bytes
    } finally {$stream.Dispose()}
}
function Get-KirPointerBytes([string]$Pointer) {
    Assert-KirInstallAncestors $Pointer
    if ([IO.Directory]::Exists($Pointer)) {Stop-KirInstall 'invalid_pointer' 'active pointer is not a regular file'}
    if (-not [IO.File]::Exists($Pointer)) {return [pscustomobject]@{Hash='absent';Bytes=$null}}
    $info=Get-Item -LiteralPath $Pointer -Force
    if ($info.Length -le 0 -or $info.Length -gt 65536) {Stop-KirInstall 'invalid_pointer' 'manifest size is outside bounds'}
    $bytes=Read-KirInstallBytes $Pointer 65536
    return [pscustomobject]@{Hash=(Get-KirSha $bytes);Bytes=$bytes}
}
function Assert-KirCurrentHash([string]$Pointer,[string]$Expected) {
    $current=Get-KirPointerBytes $Pointer
    if ($current.Hash -cne $Expected) {Stop-KirInstall 'stale_manifest' 'current pointer differs from the explicitly expected bytes'}
    return $current
}

function Read-KirManifestBytes([byte[]]$Bytes,[switch]$Template) {
    if ($null -eq $Bytes -or $Bytes.Length -eq 0 -or $Bytes.Length -gt 65536) {Stop-KirInstall 'invalid_manifest' 'manifest byte budget exceeded'}
    $settings=[Xml.XmlReaderSettings]::new();$settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit;$settings.XmlResolver=$null;$settings.MaxCharactersInDocument=65536
    $stream=[IO.MemoryStream]::new($Bytes,$false);$reader=[Xml.XmlReader]::Create($stream,$settings)
    try {$document=[Xml.XmlDocument]::new();$document.XmlResolver=$null;$document.Load($reader)}
    catch {Stop-KirInstall 'invalid_manifest' 'manifest is not supported DTD-free XML'}
    finally {$reader.Dispose();$stream.Dispose()}
    $root=$document.DocumentElement
    if ($root.LocalName -cne 'RevitAddIns' -or $root.NamespaceURI -cne '' -or $root.Attributes.Count -ne 0) {Stop-KirInstall 'foreign_manifest' 'unsupported Revit manifest root'}
    $entries=@($root.ChildNodes | Where-Object {$_.NodeType -eq [Xml.XmlNodeType]::Element})
    if ($entries.Count -ne 1 -or $entries[0].LocalName -cne 'AddIn' -or $entries[0].GetAttribute('Type') -cne 'Application' -or $entries[0].Attributes.Count -ne 1) {
        Stop-KirInstall 'foreign_manifest' 'expected one KIR Application entry'
    }
    $entry=$entries[0];$names=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($child in $entry.ChildNodes) {
        if ($child.NodeType -ne [Xml.XmlNodeType]::Element) {continue}
        if ($child.NamespaceURI -cne '' -or $child.Attributes.Count -ne 0 -or -not $names.Add($child.LocalName) -or
            $child.LocalName -cnotin @('Name','Assembly','AddInId','FullClassName','VendorId','VendorDescription')) {Stop-KirInstall 'foreign_manifest' 'unknown or duplicated manifest field'}
        if (@($child.ChildNodes | Where-Object {$_.NodeType -eq [Xml.XmlNodeType]::Element}).Count -gt 0) {Stop-KirInstall 'foreign_manifest' 'nested manifest values are unsupported'}
    }
    if ($names.Count -ne 6) {Stop-KirInstall 'foreign_manifest' 'incomplete manifest entry'}
    if ([string]::IsNullOrWhiteSpace($entry.SelectSingleNode('Name').InnerText)) {Stop-KirInstall 'foreign_manifest' 'application name must be nonempty'}
    $id=[Guid]::Empty
    if (-not [Guid]::TryParse($entry.SelectSingleNode('AddInId').InnerText,[ref]$id) -or $id.ToString('D') -cne $script:KirAddinId -or
        $entry.SelectSingleNode('FullClassName').InnerText -cne 'Kir.Revit.Connector.App' -or $entry.SelectSingleNode('VendorId').InnerText -cne 'KIR') {
        Stop-KirInstall 'foreign_manifest' 'manifest does not identify the expected KIR application'
    }
    $assembly=$entry.SelectSingleNode('Assembly').InnerText
    $markers=@($document.SelectNodes('//comment()') | Where-Object {$_.Value.Trim().StartsWith('kir-install/',[StringComparison]::Ordinal)})
    $operation=$null;$package=$null
    if ($Template) {
        if ($assembly -cne 'Kir.Revit.Connector.dll' -or $markers.Count -ne 0) {Stop-KirInstall 'invalid_manifest_template' 'template must name only the expected DLL and no activation marker'}
    } elseif ($markers.Count -gt 0) {
        if ($markers.Count -ne 1 -or $markers[0].Value.Trim() -cnotmatch '\Akir-install/1 operation=([0-9a-f-]{36}) package=([0-9a-f]{64})\z') {Stop-KirInstall 'foreign_manifest' 'invalid activation marker'}
        $operation=Get-KirOperationId $Matches[1];$package=$Matches[2]
    }
    return [pscustomobject]@{Document=$document;Assembly=$assembly;OperationId=$operation;PackageId=$package}
}
function Read-KirPackageTemplate($Package) {
    $bytes=Read-KirInstallBytes (Join-Path $Package.Directory 'Kir.Revit.Connector.addin.template') 65536
    $entry=@($Package.Files | Where-Object {$_.path -ceq 'Kir.Revit.Connector.addin.template'})
    if ($entry.Count -ne 1 -or (Get-KirSha $bytes) -cne $entry[0].sha256) {Stop-KirInstall 'package_template_changed' 'template bytes differ from the verified package'}
    Read-KirManifestBytes $bytes -Template | Out-Null
    return ,$bytes
}
function Get-KirOwnedManifest([byte[]]$Bytes,[string]$Pointer,[string]$ReleaseRoot,[string]$Year) {
    if ($null -eq $Bytes) {return [pscustomobject]@{Kind='absent';PackageId=$null}}
    $parsed=Read-KirManifestBytes $Bytes
    $assembly=Get-KirInstallPath $parsed.Assembly
    $legacy=Join-Path ([IO.Path]::GetDirectoryName($Pointer)) 'KIR.Connector/Kir.Revit.Connector.dll'
    if ($null -eq $parsed.OperationId -and (Test-KirSamePath $assembly $legacy)) {return [pscustomobject]@{Kind='legacy_pointer_only';PackageId=$null}}
    if ($null -eq $parsed.PackageId -or -not (Test-KirSamePath $assembly (Join-Path $ReleaseRoot ($Year+'/'+$parsed.PackageId+'/Kir.Revit.Connector.dll')))) {
        Stop-KirInstall 'foreign_pointer_location' 'active entry is outside the recognized release/legacy locations'
    }
    return [pscustomobject]@{Kind='managed_release';PackageId=$parsed.PackageId;OperationId=$parsed.OperationId}
}
function New-KirManifestBytes([byte[]]$Template,[string]$ReleaseDirectory,[string]$Operation,[string]$PackageId) {
    $parsed=Read-KirManifestBytes $Template -Template
    $document=$parsed.Document
    $document.SelectSingleNode('/RevitAddIns/AddIn/Assembly').InnerText=Join-Path $ReleaseDirectory 'Kir.Revit.Connector.dll'
    $comment=$document.CreateComment('kir-install/1 operation='+$Operation+' package='+$PackageId)
    $document.InsertBefore($comment,$document.DocumentElement) | Out-Null
    $settings=[Xml.XmlWriterSettings]::new();$settings.Encoding=[Text.UTF8Encoding]::new($false);$settings.Indent=$true;$settings.NewLineHandling=[Xml.NewLineHandling]::Entitize
    $stream=[IO.MemoryStream]::new();$writer=[Xml.XmlWriter]::Create($stream,$settings)
    try {$document.Save($writer);$writer.Flush();return ,$stream.ToArray()} finally {$writer.Dispose();$stream.Dispose()}
}

function Open-KirInstallLease([string]$ManifestDirectory,[switch]$ExistingOnly) {
    Assert-KirInstallAncestors $ManifestDirectory
    if (-not [IO.Directory]::Exists($ManifestDirectory)) {
        if ($ExistingOnly) {Stop-KirInstall 'installation_unavailable' 'manifest directory is absent'}
        [IO.Directory]::CreateDirectory($ManifestDirectory) | Out-Null
    }
    $path=Join-Path $ManifestDirectory $script:KirLeaseName
    Assert-KirInstallAncestors $path
    $mode=if ($ExistingOnly) {[IO.FileMode]::Open} else {[IO.FileMode]::OpenOrCreate}
    try {$stream=[IO.FileStream]::new($path,$mode,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
    catch {Stop-KirInstall 'installation_busy' 'exclusive lease for this actual pointer is unavailable'}
    if ($stream.Length -ne 0) {$stream.Dispose();Stop-KirInstall 'foreign_install_lease' 'reserved lease file is not empty'}
    return $stream
}

function Get-KirInstallObservation([string]$Pointer,[string]$PreviousHash,[string]$NextHash) {
    try {$actual=(Get-KirPointerBytes $Pointer).Hash}
    catch {return [pscustomobject]@{state='unavailable';sha256=$null}}
    $state=if ($actual -ceq $NextHash) {'matches_next'} elseif ($actual -ceq $PreviousHash) {'matches_previous'} elseif ($actual -ceq 'absent') {'absent'} else {'other'}
    return [pscustomobject]@{state=$state;sha256=$actual}
}

function New-KirInstallIntent([string]$ManifestDirectory,$Data,[byte[]]$Previous,[byte[]]$Next) {
    $directory=Join-Path $ManifestDirectory ($script:KirLedgerName+'/'+$Data.operation_id)
    Assert-KirInstallAncestors $directory
    if (Test-Path -LiteralPath $directory) {Stop-KirInstall 'install_operation_exists' 'activation operation directory already exists'}
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    if ($null -ne $Previous) {Write-KirNewBytes (Join-Path $directory 'previous.manifest') $Previous}
    if ($null -ne $Next) {Write-KirNewBytes (Join-Path $directory 'next.manifest') $Next}
    $bytes=ConvertTo-KirJsonBytes $Data
    Write-KirNewBytes (Join-Path $directory 'intent.json') $bytes
    Write-KirNewBytes (Join-Path $directory 'intent.sha256') ([Text.Encoding]::ASCII.GetBytes((Get-KirSha $bytes)))
    return Join-Path $directory 'intent.json'
}

function Read-KirInstallIntent([string]$ReceiptPath,[switch]$InstallOnly) {
    $path=Get-KirInstallPath $ReceiptPath
    Assert-KirInstallAncestors $path
    if ([IO.Path]::GetFileName($path) -cne 'intent.json') {Stop-KirInstall 'invalid_receipt_path' 'expected the fixed intent.json filename'}
    $operationDirectory=[IO.Path]::GetDirectoryName($path)
    $operation=Get-KirOperationId ([IO.Path]::GetFileName($operationDirectory))
    $ledger=[IO.Path]::GetDirectoryName($operationDirectory)
    if ([IO.Path]::GetFileName($ledger) -cne $script:KirLedgerName) {Stop-KirInstall 'invalid_receipt_path' 'receipt is not under the fixed activation ledger'}
    $manifestDirectory=[IO.Path]::GetDirectoryName($ledger)
    $bytes=Read-KirInstallBytes $path 65536
    $checksum=[Text.Encoding]::ASCII.GetString((Read-KirInstallBytes (Join-Path $operationDirectory 'intent.sha256') 64))
    if ($checksum -cne (Get-KirSha $bytes)) {Stop-KirInstall 'invalid_receipt' 'intent checksum differs'}
    # Parse exactly the bytes whose checksum was checked, not a second file read.
    $text=[Text.UTF8Encoding]::new($false,$true).GetString($bytes)
    if ($text.StartsWith([string][char]0xfeff,[StringComparison]::Ordinal)) {Stop-KirInstall 'invalid_receipt' 'receipt BOM refused'}
    $json=[Text.Json.JsonDocument]::Parse($text)
    try {
        $value=$json.RootElement
        Assert-KirJsonKeys $value @('schema','operation_id','action','revit_version','pointer_path','release_root','package_id','previous_sha256','next_sha256',
            'previous_ref','next_ref','previous_kind','rollback_of','load_verified','dependency_binding_verified')
        if ((Get-KirJsonText $value 'schema') -cne $script:KirIntentSchema -or (Get-KirJsonText $value 'operation_id') -cne $operation) {Stop-KirInstall 'invalid_receipt' 'receipt schema/operation mismatch'}
        $pointer=Join-Path $manifestDirectory $script:KirPointerName
        if (-not (Test-KirSamePath (Get-KirJsonText $value 'pointer_path') $pointer)) {Stop-KirInstall 'invalid_receipt' 'receipt does not own this actual pointer location'}
        $year=Get-KirJsonText $value 'revit_version'
        if ($year -cnotin @('2021','2022','2023','2024','2025','2026')) {Stop-KirInstall 'invalid_receipt' 'unsupported receipt year'}
        $releaseRoot=Get-KirInstallPath (Get-KirJsonText $value 'release_root')
        $package=Get-KirExpectedHash (Get-KirJsonText $value 'package_id')
        $action=Get-KirJsonText $value 'action'
        if ($action -cnotin @('install','rollback')) {Stop-KirInstall 'invalid_receipt' 'unsupported action'}
        if ($InstallOnly -and $action -cne 'install') {Stop-KirInstall 'invalid_receipt' 'rollback origin must be a direct installation'}
        foreach ($flag in @('load_verified','dependency_binding_verified')) {if ($value.GetProperty($flag).ValueKind -ne [Text.Json.JsonValueKind]::False) {Stop-KirInstall 'invalid_receipt' 'receipt cannot claim loader verification'}}
        $backups=@{}
        foreach ($side in @('previous','next')) {
            $hash=Get-KirExpectedHash (Get-KirJsonText $value ($side+'_sha256')) -AllowAbsent
            $reference=$value.GetProperty($side+'_ref')
            if ($hash -ceq 'absent') {
                if ($reference.ValueKind -ne [Text.Json.JsonValueKind]::Null) {Stop-KirInstall 'invalid_receipt' 'absent pointer has a backup reference'}
                $content=$null
            } else {
                if ($reference.ValueKind -ne [Text.Json.JsonValueKind]::String -or $reference.GetString() -cne ($side+'.manifest')) {Stop-KirInstall 'invalid_receipt' 'backup reference is not a fixed relative name'}
                $backup=Join-Path $operationDirectory ($side+'.manifest');Assert-KirInstallAncestors $backup
                $content=Read-KirInstallBytes $backup 65536
                if ((Get-KirSha $content) -cne $hash) {Stop-KirInstall 'invalid_receipt' 'backup bytes differ from recorded hash'}
                $owned=Get-KirOwnedManifest $content $pointer $releaseRoot $year
                if ($side -ceq 'next' -and $action -ceq 'install' -and ($owned.Kind -cne 'managed_release' -or $owned.PackageId -cne $package -or $owned.OperationId -cne $operation)) {
                    Stop-KirInstall 'invalid_receipt' 'new manifest marker/package differs from installation intent'
                }
            }
            $backups[$side]=[pscustomobject]@{Hash=$hash;Bytes=$content}
        }
        if ($action -ceq 'install' -and ($backups.next.Hash -ceq 'absent' -or $value.GetProperty('rollback_of').ValueKind -ne [Text.Json.JsonValueKind]::Null)) {Stop-KirInstall 'invalid_receipt' 'installation requires a next pointer and no rollback source'}
        $rollback=$null
        if ($action -ceq 'rollback') {
            $rollback=Get-KirOperationId (Get-KirJsonText $value 'rollback_of')
            $original=Read-KirInstallIntent (Join-Path $ledger ($rollback+'/intent.json')) -InstallOnly
            if (-not (Test-KirSamePath $original.Pointer $pointer) -or -not (Test-KirSamePath $original.ReleaseRoot $releaseRoot) -or
                $original.Year -cne $year -or $original.PackageId -cne $package -or $original.Next.Hash -cne $backups.previous.Hash -or
                $original.Previous.Hash -cne $backups.next.Hash -or -not (Test-KirAttemptMarker $original)) {
                Stop-KirInstall 'invalid_receipt' 'rollback is not the exact reversal of its owned installation record'
            }
        }
        $previousKind=Get-KirJsonText $value 'previous_kind'
        if ($previousKind -cne (Get-KirOwnedManifest $backups.previous.Bytes $pointer $releaseRoot $year).Kind) {Stop-KirInstall 'invalid_receipt' 'previous pointer classification differs'}
        return [pscustomobject]@{Path=$path;Directory=$operationDirectory;OperationId=$operation;Action=$action;Year=$year;Pointer=$pointer;
            ManifestDirectory=$manifestDirectory;ReleaseRoot=$releaseRoot;PackageId=$package;Previous=$backups.previous;Next=$backups.next;PreviousKind=$previousKind;RollbackOf=$rollback}
    } finally {$json.Dispose()}
}
