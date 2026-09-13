#requires -Version 7.4
# Packaging-only contract. No Revit loading, installation or runtime admission.
Set-StrictMode -Version Latest
$script:KirPackageSchema = 'kir-revit-package/1'
$script:KirPackageMaxFiles = 2048
$script:KirPackageMaxManifestBytes = 1048576
$script:KirPackageMaxFileBytes = 536870912L
$script:KirPackageMaxTotalBytes = 2147483648L

function Stop-KirPackage([string]$Code, [string]$Message) { throw ($Code + ': ' + $Message) }

function Get-KirAvailableBuildBytes([string]$Path) {
    # Read-only mount lookup. Do not create the requested output directory merely
    # to check its volume. Longest matching mount wins, including nested mounts.
    $full=[IO.Path]::GetFullPath($Path)
    $candidates=@([IO.DriveInfo]::GetDrives() | Where-Object {
        $relative=[IO.Path]::GetRelativePath($_.RootDirectory.FullName,$full).Replace('\','/')
        $relative -ceq '.' -or ($relative -cne '..' -and -not $relative.StartsWith('../',[StringComparison]::Ordinal) -and -not [IO.Path]::IsPathRooted($relative))
    } | Sort-Object {$_.RootDirectory.FullName.Length} -Descending)
    if ($candidates.Count -eq 0) {Stop-KirPackage 'build_space_unavailable' 'cannot identify the output volume; no build started'}
    try {return [long]$candidates[0].AvailableFreeSpace}
    catch {Stop-KirPackage 'build_space_unavailable' 'cannot measure available output-volume space; no build started'}
}

function Assert-KirBuildSpace([string]$Path,[long]$MinimumFreeBytes) {
    if ($MinimumFreeBytes -le 0) {Stop-KirPackage 'build_space_policy_invalid' 'minimum free space must be positive'}
    $available=Get-KirAvailableBuildBytes $Path
    if ($available -lt $MinimumFreeBytes) {
        Stop-KirPackage 'build_space_insufficient' ('available='+$available+' required='+$MinimumFreeBytes+' bytes; retain existing files and resolve capacity before retry')
    }
}

function Assert-KirBuildPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -match '[;,%$="''\r\n]') {
        Stop-KirPackage 'build_path_unsupported' 'path has unsupported MSBuild/command metacharacters'
    }
}

function Get-KirSha([byte[]]$Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}

function Write-KirNewBytes([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::WriteThrough)
    try { $stream.Write($Bytes,0,$Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

function ConvertTo-KirJsonBytes($Value) {
    return ,([Text.UTF8Encoding]::new($false,$true).GetBytes((ConvertTo-Json -InputObject $Value -Depth 12 -Compress)))
}

function Assert-KirRelativePath([string]$Path) {
    if ([string]::IsNullOrEmpty($Path) -or $Path.Length -gt 512 -or $Path.Contains('\') -or [IO.Path]::IsPathRooted($Path)) {
        Stop-KirPackage 'package_path_invalid' 'expected a bounded portable relative path'
    }
    foreach ($part in $Path.Split('/')) {
        if ($part -in @('','.','..') -or $part -notmatch '\A[A-Za-z0-9_.-]+\z' -or $part.EndsWith('.') `
            -or $part -match '\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            Stop-KirPackage 'package_path_invalid' 'Windows aliases, devices and nonportable path segments are refused'
        }
    }
}

function Assert-KirNotLink([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-KirPackage 'package_link_refused' 'links/reparse points are not package inputs'
    }
}

function Get-KirInventory([string]$Root, [switch]$ExcludeManifest) {
    Assert-KirNotLink $Root
    $rows = [Collections.Generic.List[object]]::new()
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $pending = [Collections.Generic.Queue[string]]::new()
    $pending.Enqueue([IO.Path]::GetFullPath($Root))
    [long]$total = 0
    while ($pending.Count -gt 0) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Dequeue() -Force) {
            Assert-KirNotLink $item.FullName
            $relative = [IO.Path]::GetRelativePath($Root,$item.FullName).Replace('\','/')
            Assert-KirRelativePath $relative
            if (-not $names.Add($relative)) { Stop-KirPackage 'package_path_collision' 'case-insensitive package paths collide' }
            if ($item.PSIsContainer) { $pending.Enqueue($item.FullName); continue }
            if ($ExcludeManifest -and $relative -ceq 'package.json') { continue }
            if ($rows.Count -ge $script:KirPackageMaxFiles -or $item.Length -gt $script:KirPackageMaxFileBytes) {
                Stop-KirPackage 'package_budget_exceeded' 'package file count/size exceeded'
            }
            $total += $item.Length
            if ($total -gt $script:KirPackageMaxTotalBytes) { Stop-KirPackage 'package_budget_exceeded' 'package total size exceeded' }
            $rows.Add([ordered]@{path=$relative; size=[long]$item.Length; sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()})
        }
    }
    return ,@($rows | Sort-Object { $_.path } -CaseSensitive)
}

function Copy-KirTree([string]$Source, [string]$Destination) {
    $inventory = Get-KirInventory $Source
    [IO.Directory]::CreateDirectory($Destination) | Out-Null
    foreach ($row in $inventory) {
        $target = Join-Path $Destination $row.path
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        [IO.File]::Copy((Join-Path $Source $row.path),$target,$false)
    }
}

function Assert-KirJsonKeys([Text.Json.JsonElement]$Element, [string[]]$Expected) {
    if ($Element.ValueKind -ne [Text.Json.JsonValueKind]::Object) { Stop-KirPackage 'package_manifest_invalid' 'expected JSON object' }
    $keys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($property in $Element.EnumerateObject()) {
        if (-not $keys.Add($property.Name) -or $property.Name -cnotin $Expected) {
            Stop-KirPackage 'package_manifest_invalid' 'duplicate/unknown JSON property'
        }
    }
    if ($keys.Count -ne $Expected.Count) { Stop-KirPackage 'package_manifest_invalid' 'missing JSON property' }
}

function Get-KirJsonText([Text.Json.JsonElement]$Object,[string]$Name) {
    $value = $Object.GetProperty($Name)
    if ($value.ValueKind -ne [Text.Json.JsonValueKind]::String) { Stop-KirPackage 'package_manifest_invalid' 'expected text field' }
    return $value.GetString()
}

function Assert-KirRoleInventory($Rows) {
    $paths = @($Rows | ForEach-Object { $_.path })
    foreach ($required in @('Kir.Revit.Connector.dll','Kir.Revit.Protocol.dll','Kir.Revit.Connector.addin.template',
                            'compiler/Kir.Revit.CompilerHost.exe','client/Kir.Revit.PipeClient.exe')) {
        if ($required -cnotin $paths) { Stop-KirPackage 'package_component_missing' ('required component: ' + $required) }
    }
    foreach ($row in $Rows) {
        $leaf = [IO.Path]::GetFileName($row.path)
        if ($leaf -in @('RevitAPI.dll','RevitAPIUI.dll','AdWindows.dll','UIFramework.dll') -or $row.path -match '(^|/)ref/') {
            Stop-KirPackage 'package_forbidden_dependency' 'Revit/reference binaries cannot be redistributed in this package'
        }
        if (-not $row.path.Contains('/') -and $leaf -in @('WindowsBase.dll','PresentationCore.dll','PresentationFramework.dll',
            'System.Windows.Forms.dll','System.Private.CoreLib.dll','coreclr.dll','hostfxr.dll','clrjit.dll')) {
            Stop-KirPackage 'package_forbidden_dependency' 'unexpected desktop/runtime binary beside the add-in'
        }
        if ($row.path.Contains('/') -and -not ($row.path.StartsWith('compiler/') -or $row.path.StartsWith('client/'))) {
            Stop-KirPackage 'package_role_invalid' 'unknown package subdirectory'
        }
    }
}

function Read-KirJsonDocument([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -gt 8388608) { Stop-KirPackage 'package_runtime_invalid' 'runtime metadata exceeds 8 MiB' }
    $text = [Text.UTF8Encoding]::new($false,$true).GetString($bytes)
    if ($text.StartsWith([string][char]0xfeff,[StringComparison]::Ordinal)) { Stop-KirPackage 'package_runtime_invalid' 'runtime metadata BOM refused' }
    $document = [Text.Json.JsonDocument]::Parse($text)
    try {
        $pending = [Collections.Generic.Stack[Text.Json.JsonElement]]::new()
        $pending.Push($document.RootElement)
        while ($pending.Count -gt 0) {
            $value = $pending.Pop()
            if ($value.ValueKind -eq [Text.Json.JsonValueKind]::Object) {
                $keys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
                foreach ($property in $value.EnumerateObject()) {
                    if (-not $keys.Add($property.Name)) { Stop-KirPackage 'package_runtime_invalid' 'duplicate runtime JSON key' }
                    $pending.Push($property.Value)
                }
            } elseif ($value.ValueKind -eq [Text.Json.JsonValueKind]::Array) {
                foreach ($item in $value.EnumerateArray()) { $pending.Push($item) }
            }
        }
        return $document
    } catch { $document.Dispose(); throw }
}

function Assert-KirRuntimeRole([string]$Root,[string]$Role,[string]$AssemblyName) {
    $directory = Join-Path $Root $Role
    foreach ($name in @("$AssemblyName.exe","$AssemblyName.dll","$AssemblyName.deps.json","$AssemblyName.runtimeconfig.json",
                         'Kir.Revit.Protocol.dll','coreclr.dll','hostfxr.dll','hostpolicy.dll','System.Private.CoreLib.dll')) {
        if (-not [IO.File]::Exists((Join-Path $directory $name))) { Stop-KirPackage 'package_runtime_incomplete' ('missing ' + $Role + '/' + $name) }
    }
    $config = Read-KirJsonDocument (Join-Path $directory "$AssemblyName.runtimeconfig.json")
    $deps = $null
    try {
        $runtime = $config.RootElement.GetProperty('runtimeOptions')
        if ((Get-KirJsonText $runtime 'tfm') -cne 'net8.0') { Stop-KirPackage 'package_runtime_invalid' 'helper must target net8.0' }
        $keys = @($runtime.EnumerateObject() | ForEach-Object Name)
        if ('framework' -cin $keys -or 'frameworks' -cin $keys) { Stop-KirPackage 'package_runtime_invalid' 'framework-dependent helper is refused' }
        $included = $runtime.GetProperty('includedFrameworks')
        if ($included.ValueKind -ne [Text.Json.JsonValueKind]::Array -or $included.GetArrayLength() -ne 1 `
            -or (Get-KirJsonText $included[0] 'name') -cne 'Microsoft.NETCore.App' `
            -or (Get-KirJsonText $included[0] 'version') -cnotmatch '\A8\.\d+\.\d+\z') {
            Stop-KirPackage 'package_runtime_invalid' 'expected bundled .NET8 Core runtime'
        }
        $deps = Read-KirJsonDocument (Join-Path $directory "$AssemblyName.deps.json")
        $targetName = Get-KirJsonText ($deps.RootElement.GetProperty('runtimeTarget')) 'name'
        if (-not $targetName.EndsWith('/win-x64',[StringComparison]::Ordinal)) { Stop-KirPackage 'package_runtime_invalid' 'helper deps target must be win-x64' }
        $target = $deps.RootElement.GetProperty('targets').GetProperty($targetName)
        $libraries = @($target.EnumerateObject())
        $appLibraries = @($libraries | Where-Object { $_.Name.StartsWith($AssemblyName + '/', [StringComparison]::Ordinal) })
        if ($appLibraries.Count -ne 1 -or $appLibraries[0].Value.GetProperty('runtime').GetProperty($AssemblyName + '.dll').ValueKind -ne [Text.Json.JsonValueKind]::Object) {
            Stop-KirPackage 'package_runtime_invalid' 'deps must declare the executable managed assembly'
        }
        $runtimeVersion = Get-KirJsonText $included[0] 'version'
        $runtimePack = @($libraries | Where-Object { $_.Name -ceq ('runtimepack.Microsoft.NETCore.App.Runtime.win-x64/' + $runtimeVersion) })
        if ($runtimePack.Count -ne 1) { Stop-KirPackage 'package_runtime_invalid' 'deps runtime pack must match bundled runtime configuration' }
        if ($runtimePack[0].Value.GetProperty('runtime').GetProperty('System.Private.CoreLib.dll').ValueKind -ne [Text.Json.JsonValueKind]::Object) {
            Stop-KirPackage 'package_runtime_invalid' 'deps runtime pack must declare CoreLib'
        }
        foreach ($library in $target.EnumerateObject()) {
            foreach ($group in $library.Value.EnumerateObject()) {
                if ($group.Name -cnotin @('runtime','native','resources','runtimeTargets')) { continue }
                foreach ($asset in $group.Value.EnumerateObject()) {
                    $assetPath = $asset.Name.Replace('\','/')
                    Assert-KirRelativePath $assetPath
                    $leaf = [IO.Path]::GetFileName($assetPath)
                    if ($leaf -ceq '_._') { continue }
                    if ($group.Name -ceq 'resources') {
                        $locale = Get-KirJsonText $asset.Value 'locale'; Assert-KirRelativePath $locale
                        $relative = $locale + '/' + $leaf
                    } else { $relative = $leaf }
                    if (-not [IO.File]::Exists((Join-Path $directory $relative))) {
                        Stop-KirPackage 'package_runtime_incomplete' ('declared runtime asset missing: ' + $Role + '/' + $relative)
                    }
                }
            }
        }
    } finally { $config.Dispose(); if ($null -ne $deps) { $deps.Dispose() } }
}

function Get-KirManagedIdentity([string]$Path) {
    $identity = [Reflection.AssemblyName]::GetAssemblyName($Path)
    $stream = [IO.File]::OpenRead($Path)
    $pe = [Reflection.PortableExecutable.PEReader]::new($stream)
    try {
        $metadata = [Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($pe)
        $references = @(
            foreach ($handle in $metadata.AssemblyReferences) {
                $reference = $metadata.GetAssemblyReference($handle)
                $key = $metadata.GetBlobBytes($reference.PublicKeyOrToken)
                if (($reference.Flags -band [Reflection.AssemblyFlags]::PublicKey) -ne 0) {
                    $fullHash = [Security.Cryptography.SHA1]::HashData($key)
                    $key = $fullHash[($fullHash.Length-8)..($fullHash.Length-1)]; [Array]::Reverse($key)
                }
                [pscustomobject]@{Name=$metadata.GetString($reference.Name);Version=$reference.Version;
                    Token=[Convert]::ToHexString([byte[]]$key).ToLowerInvariant();Culture=$metadata.GetString($reference.Culture)}
            }
        )
        return [pscustomobject]@{Name=$identity.Name;Version=$identity.Version;
            Token=[Convert]::ToHexString($identity.GetPublicKeyToken()).ToLowerInvariant();Culture=$identity.CultureName;References=$references}
    } finally {$pe.Dispose();$stream.Dispose()}
}

function Assert-KirAddinClosure([string]$Root,[string]$Year) {
    $warnings=[Collections.Generic.List[object]]::new()
    $local = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Filter '*.dll') {
        $identity = Get-KirManagedIdentity $file.FullName
        if ($identity.Name -ine $file.BaseName -or $local.ContainsKey($identity.Name)) {
            Stop-KirPackage 'package_addin_identity_invalid' 'root DLL identity differs from its name or is duplicated'
        }
        $local.Add($identity.Name,$identity)
    }
    $platform = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    if ([int]$Year -ge 2025) {
        # Only the already validated bundled Microsoft.NETCore.App runtime-pack
        # assets establish this packaging profile's CoreCLR-provided names.
        # This is not a wildcard System.* exemption or WindowsDesktop proof.
        $deps = Read-KirJsonDocument (Join-Path $Root 'client/Kir.Revit.PipeClient.deps.json')
        try {
            $targetName=Get-KirJsonText ($deps.RootElement.GetProperty('runtimeTarget')) 'name'
            $target=$deps.RootElement.GetProperty('targets').GetProperty($targetName)
            foreach ($library in $target.EnumerateObject()) {
                if (-not $library.Name.StartsWith('runtimepack.Microsoft.NETCore.App.Runtime.win-x64/',[StringComparison]::Ordinal)) {continue}
                foreach ($asset in $library.Value.GetProperty('runtime').EnumerateObject()) {
                    $leaf=[IO.Path]::GetFileName($asset.Name)
                    if (-not $leaf.EndsWith('.dll',[StringComparison]::OrdinalIgnoreCase)) {continue}
                    $identity=Get-KirManagedIdentity (Join-Path $Root ('client/'+$leaf))
                    if ($identity.Name -ine [IO.Path]::GetFileNameWithoutExtension($leaf)) {Stop-KirPackage 'package_runtime_invalid' 'runtime asset identity mismatch'}
                    $platform.Add($identity.Name,$identity)
                }
            }
        } finally {$deps.Dispose()}
    }
    foreach ($identity in $local.Values) {
        foreach ($reference in $identity.References) {
            if ($local.ContainsKey($reference.Name)) {
                $provided=$local[$reference.Name]
                if ($provided.Version.CompareTo($reference.Version) -lt 0 -or $provided.Token -cne $reference.Token -or $provided.Culture -ine $reference.Culture) {
                    Stop-KirPackage 'package_addin_identity_invalid' 'included dependency has lower version or different token/culture'
                }
                if ($provided.Version -ne $reference.Version) {
                    # File presence is not CLR compatibility. In particular,
                    # .NET Framework normally binds exact assembly versions.
                    $warnings.Add([pscustomobject]@{requester=$identity.Name;dependency=$reference.Name;
                        expected_version=$reference.Version.ToString();provided_version=$provided.Version.ToString();
                        status='requires_windows_loader_validation'})
                }
            } elseif ($reference.Name -cin @('RevitAPI','RevitAPIUI')) {
                if ($reference.Version.Major -ne ([int]$Year-2000)) {Stop-KirPackage 'package_reference_year_mismatch' 'addon references another Revit year'}
            } elseif ([int]$Year -lt 2025 -and $reference.Name -cin @('mscorlib','System','System.Core','System.Numerics','netstandard')) {
                $expectedVersion=if ($reference.Name -ceq 'netstandard') {'2.0.0.0'} else {'4.0.0.0'}
                $expectedToken=if ($reference.Name -ceq 'netstandard') {'cc7b13ffcd2ddd51'} else {'b77a5c561934e089'}
                if ($reference.Version.ToString() -cne $expectedVersion -or $reference.Token -cne $expectedToken -or $reference.Culture -cne '') {
                    Stop-KirPackage 'package_host_reference_unsupported' 'unsupported legacy CLR/facade identity'
                }
            } elseif ([int]$Year -ge 2025 -and $platform.ContainsKey($reference.Name)) {
                $provided=$platform[$reference.Name]
                if ($provided.Version.CompareTo($reference.Version) -lt 0 -or $provided.Token -cne $reference.Token -or $provided.Culture -ine $reference.Culture) {
                    Stop-KirPackage 'package_host_reference_unsupported' 'bundled Core runtime identity cannot supply the declared reference'
                }
                if ($provided.Version -ne $reference.Version) {
                    $warnings.Add([pscustomobject]@{requester=$identity.Name;dependency=$reference.Name;
                        expected_version=$reference.Version.ToString();provided_version=$provided.Version.ToString();
                        status='requires_windows_loader_validation'})
                }
            } else {Stop-KirPackage 'package_addin_dependency_missing' ('unresolved managed reference: '+$reference.Name)}
        }
    }
    return [pscustomobject]@{BindingWarnings=@($warnings);DependencyBindingVerified=$false;LoadVerified=$false}
}

function Read-KirPackage([string]$Directory) {
    $root = [IO.Path]::GetFullPath($Directory)
    Assert-KirNotLink $root
    $manifestPath = Join-Path $root 'package.json'
    Assert-KirNotLink $manifestPath
    $info = Get-Item -LiteralPath $manifestPath
    if ($info.Length -le 0 -or $info.Length -gt $script:KirPackageMaxManifestBytes) { Stop-KirPackage 'package_manifest_invalid' 'manifest size exceeded' }
    $bytes = [IO.File]::ReadAllBytes($manifestPath)
    $utf8 = [Text.UTF8Encoding]::new($false,$true)
    $text = $utf8.GetString($bytes)
    if ($text.StartsWith([string][char]0xfeff,[StringComparison]::Ordinal)) { Stop-KirPackage 'package_manifest_invalid' 'manifest BOM is refused' }
    $json = [Text.Json.JsonDocument]::Parse($text)
    try {
        $data = $json.RootElement
        Assert-KirJsonKeys $data @('schema','revit_version','configuration','protocol','product_version','sdk_version','source_digest','runtime_identifier','files')
        if ((Get-KirJsonText $data 'schema') -cne $script:KirPackageSchema -or (Get-KirJsonText $data 'runtime_identifier') -cne 'win-x64') {
            Stop-KirPackage 'package_manifest_invalid' 'unsupported package profile'
        }
        $year = Get-KirJsonText $data 'revit_version'
        if ($year -cnotin @('2021','2022','2023','2024','2025','2026') -or (Get-KirJsonText $data 'configuration') -cnotin @('Debug','Release')) {
            Stop-KirPackage 'package_manifest_invalid' 'unsupported year/configuration'
        }
        foreach ($name in @('protocol','product_version','sdk_version')) {
            if ([string]::IsNullOrWhiteSpace((Get-KirJsonText $data $name))) { Stop-KirPackage 'package_manifest_invalid' 'missing build metadata' }
        }
        if ((Get-KirJsonText $data 'source_digest') -cnotmatch '\A[0-9a-f]{64}\z') { Stop-KirPackage 'package_manifest_invalid' 'invalid source digest' }
        $files = $data.GetProperty('files')
        if ($files.ValueKind -ne [Text.Json.JsonValueKind]::Array -or $files.GetArrayLength() -gt $script:KirPackageMaxFiles) {
            Stop-KirPackage 'package_manifest_invalid' 'invalid inventory array'
        }
        $rows = [Collections.Generic.List[object]]::new()
        $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($file in $files.EnumerateArray()) {
            Assert-KirJsonKeys $file @('path','size','sha256')
            $path = Get-KirJsonText $file 'path'; Assert-KirRelativePath $path
            if ($path -ieq 'package.json' -or -not $names.Add($path)) { Stop-KirPackage 'package_manifest_invalid' 'self/duplicate inventory entry' }
            $size = $file.GetProperty('size').GetInt64()
            $sha = Get-KirJsonText $file 'sha256'
            if ($size -lt 0 -or $size -gt $script:KirPackageMaxFileBytes -or $sha -cnotmatch '\A[0-9a-f]{64}\z') {
                Stop-KirPackage 'package_manifest_invalid' 'invalid file size/digest'
            }
            $rows.Add([ordered]@{path=$path;size=$size;sha256=$sha})
        }
        Assert-KirRoleInventory $rows
        $actual = Get-KirInventory $root -ExcludeManifest
        if ([Text.Encoding]::UTF8.GetString((ConvertTo-KirJsonBytes @($rows | Sort-Object { $_.path } -CaseSensitive))) -cne
            [Text.Encoding]::UTF8.GetString((ConvertTo-KirJsonBytes $actual))) {
            Stop-KirPackage 'package_inventory_mismatch' 'missing/extra/changed package files'
        }
        Assert-KirRuntimeRole $root 'compiler' 'Kir.Revit.CompilerHost'
        Assert-KirRuntimeRole $root 'client' 'Kir.Revit.PipeClient'
        $binding=Assert-KirAddinClosure $root $year
        return [pscustomobject]@{Directory=$root;PackageId=(Get-KirSha $bytes);RevitVersion=$year;ManifestBytes=$bytes;Files=@($rows);
            BindingWarnings=$binding.BindingWarnings;DependencyBindingVerified=$false;LoadVerified=$false}
    } finally { $json.Dispose() }
}

function Read-KirXml([string]$Path) {
    $settings = [Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing = [Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $settings.MaxCharactersInDocument = 4194304
    $reader = [Xml.XmlReader]::Create($Path,$settings)
    try { $document = [Xml.XmlDocument]::new(); $document.XmlResolver = $null; $document.Load($reader); return ,$document }
    finally { $reader.Dispose() }
}

function Copy-KirSourceSnapshot([string]$Root,[string]$Destination,[string]$SdkVersion) {
    Assert-KirNotLink $Root
    foreach ($hook in @('Directory.Build.targets','Directory.Packages.props','NuGet.Config','global.json')) {
        if (Test-Path -LiteralPath (Join-Path $Root $hook)) { Stop-KirPackage 'source_hook_unsupported' 'custom root hook/config requires explicit capture support' }
    }
    $projects = @('Kir.Revit.Protocol','Kir.Revit.Connector','Kir.Revit.CompilerHost','Kir.Revit.PipeClient')
    $propertyNames=@('RevitVersion','RevitApiVersion','LangVersion','Nullable','ImplicitUsings','Deterministic','ContinuousIntegrationBuild',
        'TreatWarningsAsErrors','NoWarn','Version','Authors','Company','Product','Copyright','TargetFramework','DefineConstants',
        'AssemblyName','RootNamespace','RevitInstallDir','UseWPF','UseWindowsForms','OutputType','PublishSingleFile','SelfContained',
        'RuntimeIdentifier','PublishTrimmed')
    $sourcePaths = [Collections.Generic.List[string]]::new()
    foreach ($top in @('Directory.Build.props','addin/Kir.Revit.Connector.addin')) {
        Assert-KirNotLink (Join-Path $Root $top); $sourcePaths.Add($top)
    }
    foreach ($name in $projects) {
        $projectRoot = Join-Path $Root ('src/' + $name)
        Assert-KirNotLink (Join-Path $Root 'src'); Assert-KirNotLink $projectRoot
        $pending = [Collections.Generic.Queue[string]]::new(); $pending.Enqueue($projectRoot)
        while ($pending.Count -gt 0) {
            foreach ($item in Get-ChildItem -LiteralPath $pending.Dequeue() -Force) {
                if ($item.PSIsContainer -and $item.Name -in @('bin','obj')) { continue }
                Assert-KirNotLink $item.FullName
                if ($item.PSIsContainer) { $pending.Enqueue($item.FullName); continue }
                $relative = [IO.Path]::GetRelativePath($Root,$item.FullName).Replace('\','/')
                Assert-KirRelativePath $relative; $sourcePaths.Add($relative)
            }
        }
    }
    if ($sourcePaths.Count -gt $script:KirPackageMaxFiles) { Stop-KirPackage 'source_snapshot_budget' 'too many source files' }
    foreach ($relative in $sourcePaths) {
        if ($relative -match '(^|/)(Directory\.(Build\.(props|targets)|Packages\.props)|NuGet\.Config|global\.json)$' -and $relative -cne 'Directory.Build.props') {
            Stop-KirPackage 'source_hook_unsupported' 'nested build/config hook requires explicit support'
        }
        $source = Join-Path $Root $relative
        if ((Get-Item -LiteralPath $source -Force).Length -gt 16777216) { Stop-KirPackage 'source_snapshot_budget' 'source file exceeds 16 MiB' }
        $destinationPath = Join-Path $Destination $relative
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destinationPath)) | Out-Null
        [IO.File]::Copy($source,$destinationPath,$false)
        if ($relative.EndsWith('.csproj') -or $relative -ceq 'Directory.Build.props') {
            # Validate the captured bytes, never re-read a concurrently edited
            # source after validation and copy a different build program.
            $xml = Read-KirXml $destinationPath
            if ($xml.DocumentElement.LocalName -cne 'Project' -or
                ($relative.EndsWith('.csproj') -and $xml.DocumentElement.GetAttribute('Sdk') -cne 'Microsoft.NET.Sdk')) {
                Stop-KirPackage 'source_hook_unsupported' 'only the declared Microsoft.NET.Sdk project profile is supported'
            }
            foreach ($attribute in $xml.DocumentElement.Attributes) {
                if ($attribute.NamespaceURI -ceq 'http://www.w3.org/2000/xmlns/') { continue }
                if ($relative.EndsWith('.csproj') -and $attribute.Name -ceq 'Sdk') { continue }
                Stop-KirPackage 'source_hook_unsupported' 'unexpected root project attribute'
            }
            if ($xml.OuterXml -match '\$\(\[|@\(|%\(') {
                Stop-KirPackage 'source_hook_unsupported' 'property functions and item/metadata expressions require explicit support'
            }
            foreach ($condition in $xml.SelectNodes('//@*[local-name()="Condition"]')) {
                $expression=[regex]::Replace($condition.Value,"'(?:\`$\([A-Za-z_][A-Za-z0-9_]*\)|[A-Za-z0-9_.-]*)'",'V')
                if ($expression -notmatch '\A\s*V\s*(==|!=)\s*V(?:\s+(Or|And)\s+V\s*(==|!=)\s*V)*\s*\z') {
                    Stop-KirPackage 'source_hook_unsupported' 'only explicit string comparison build conditions are supported'
                }
            }
            foreach ($node in $xml.DocumentElement.ChildNodes) {
                if ($node.NodeType -eq [Xml.XmlNodeType]::Element -and $node.LocalName -cnotin @('PropertyGroup','ItemGroup')) {
                    Stop-KirPackage 'source_hook_unsupported' 'unsupported project control construct'
                }
            }
            if ($xml.SelectNodes('//*[local-name()="Import" or local-name()="UsingTask" or local-name()="Target" or local-name()="Compile" or local-name()="Content" or local-name()="EmbeddedResource" or local-name()="None" or local-name()="Sdk"]').Count -gt 0) {
                Stop-KirPackage 'source_hook_unsupported' 'custom tasks/imports/source or resource includes require explicit snapshot support'
            }
            foreach ($reference in $xml.SelectNodes('//*[local-name()="ProjectReference"]')) {
                $include = $reference.GetAttribute('Include').Replace('\','/')
                if ($include.Contains('$') -or [IO.Path]::IsPathRooted($include)) { Stop-KirPackage 'source_reference_escape' 'project reference is not literal and local' }
                $resolved = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetDirectoryName($destinationPath)) $include))
                $wanted = @($projects | ForEach-Object { [IO.Path]::GetFullPath((Join-Path $Destination ('src/' + $_ + '/' + $_ + '.csproj'))) })
                if ($resolved -cnotin $wanted) { Stop-KirPackage 'source_reference_escape' 'project reference leaves known source snapshot' }
            }
            foreach ($item in $xml.SelectNodes('//*[local-name()="ItemGroup"]/*')) {
                if ($item.LocalName -cnotin @('PackageReference','ProjectReference','Reference')) {
                    Stop-KirPackage 'source_hook_unsupported' 'unsupported build item requires explicit snapshot support'
                }
                if ($item.LocalName -ceq 'Reference') {
                    $name=$item.GetAttribute('Include')
                    $hint=$item.SelectSingleNode('*[local-name()="HintPath"]')
                    if ($name -cnotin @('RevitAPI','RevitAPIUI') -or $null -eq $hint -or $hint.InnerText.Replace('\','/') -cne ('$(RevitInstallDir)/'+$name+'.dll')) {
                        Stop-KirPackage 'source_reference_escape' 'only explicit pinned Revit API references may be outside snapshot'
                    }
                }
            }
            foreach ($property in $xml.SelectNodes('//*[local-name()="PropertyGroup"]/*')) {
                if ($property.LocalName -cnotin $propertyNames) {
                    Stop-KirPackage 'source_hook_unsupported' 'unsupported source property requires explicit capture support'
                }
            }
        }
    }
    Write-KirNewBytes (Join-Path $Destination 'Directory.Build.targets') ([Text.Encoding]::UTF8.GetBytes('<Project />'))
    Write-KirNewBytes (Join-Path $Destination 'global.json') (ConvertTo-KirJsonBytes ([ordered]@{sdk=[ordered]@{version=$SdkVersion;rollForward='disable'}}))
    Write-KirNewBytes (Join-Path $Destination 'NuGet.Config') ([Text.Encoding]::UTF8.GetBytes('<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>'))
    $inventory = Get-KirInventory $Destination
    return [pscustomobject]@{Root=$Destination;Digest=(Get-KirSha (ConvertTo-KirJsonBytes $inventory));Files=$inventory}
}
