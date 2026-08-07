using System.Collections.Concurrent;
using System.Diagnostics;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

namespace CompileService;

/// <summary>
/// Compiles C# code using Roslyn with version-specific RevitAPI references.
/// Thread-safe: MetadataReferences are preloaded at startup and shared across compilations.
/// </summary>
public sealed class RoslynCompiler
{
    // Full reference matrix we ship for.  Which subset is *required* to start is
    // configurable via KUKAI_COMPILE_REQUIRED_VERSIONS (comma-separated, e.g.
    // "2025,2026") so a machine provisioning fewer NuGet ref-sets can still start —
    // but only as an explicit, logged override.  Unset/empty/malformed → the full
    // matrix (fail-closed: an empty required set would mean "require nothing").
    private static readonly string[] AllShippedVersions =
        { "2021", "2022", "2023", "2024", "2025", "2026" };

    private const string Net48ReferenceAssemblyPackageVersion = "1.0.3";

    public static IReadOnlyList<string> RequiredVersions { get; } = ResolveRequiredVersions();

    private static IReadOnlyList<string> ResolveRequiredVersions()
    {
        var raw = Environment.GetEnvironmentVariable("KUKAI_COMPILE_REQUIRED_VERSIONS");
        if (string.IsNullOrWhiteSpace(raw))
            return Array.AsReadOnly(AllShippedVersions);
        var parsed = raw
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(v => v.Length == 4 && v.All(char.IsDigit))
            .Distinct(StringComparer.Ordinal)
            .OrderBy(v => v, StringComparer.Ordinal)
            .ToArray();
        // Fail-closed: an empty/garbage override must never weaken the gate to
        // "require nothing" — fall back to the full shipped matrix.
        return parsed.Length == 0
            ? Array.AsReadOnly(AllShippedVersions)
            : Array.AsReadOnly(parsed);
    }

    private readonly ILogger<RoslynCompiler> _logger;

    // net8.0 system references (for Revit 2025-2026)
    private readonly List<MetadataReference> _net8SystemRefs;

    // net48 system references (for Revit 2021-2024)
    private readonly List<MetadataReference> _net48SystemRefs;

    // RevitAPI references per version: "2021" -> [RevitAPI.dll, RevitAPIUI.dll]
    private readonly ConcurrentDictionary<string, List<MetadataReference>> _revitRefs = new();

    // Structured record of every reference DLL we tried to load but failed.
    // Surfaced via GET /health → "failedReferences". Prevents the silent catch blocks
    // that historically masked the "Could not load Microsoft.CodeAnalysis 4.11.0.0" class of
    // errors in production (≈143/week with zero visibility).
    private static readonly ConcurrentBag<FailedReference> _failedReferences = new();

    public static IReadOnlyCollection<FailedReference> FailedReferences => _failedReferences;

    // All available Revit versions
    public IReadOnlyList<string> AvailableVersions { get; }
    public IReadOnlyList<string> MissingVersions { get; }
    public int Net8SystemReferenceCount => _net8SystemRefs.Count;
    public int Net48SystemReferenceCount => _net48SystemRefs.Count;

    /// <summary>
    /// Revit 2025+ targets .NET 8; 2021-2024 target .NET Framework 4.8.  Single
    /// source of truth for the target-framework split, used by both the compile
    /// path and the startup readiness gate so the two can never drift.
    /// </summary>
    public static bool IsNet8Target(string revitVersion) =>
        int.TryParse(revitVersion, out var year) && year >= 2025;

    /// <summary>
    /// True when the system reference sets required by the *configured* Revit
    /// versions are all loaded.  A gate configured for only net8-era versions
    /// (2025+) must not demand the net48 framework references it will never use,
    /// and vice versa — but every framework a required version DOES target must
    /// be present (fail-closed per framework, not per irrelevant condition).
    /// </summary>
    public bool SystemReferenceSetsReady
    {
        get
        {
            var requiresNet8 = RequiredVersions.Any(IsNet8Target);
            var requiresNet48 = RequiredVersions.Any(v => !IsNet8Target(v));
            return (!requiresNet8 || _net8SystemRefs.Count > 0)
                && (!requiresNet48 || _net48SystemRefs.Count > 0);
        }
    }

    private static readonly string[] AllowedPrefixes =
    {
        "System.Runtime",
        "System.Private.CoreLib",
        "System.Core",          // LINQ extension methods live here in .NET Framework 4.8
        "System.Collections",
        "System.Linq",
        "System.Text.RegularExpressions",
        "System.Text.Encoding",
        "System.Memory",
        "System.Buffers",
        "System.Numerics",
        "System.ObjectModel",
        "System.ComponentModel",
        "System.Console",
        "netstandard",
        "mscorlib",
    };

    // Assemblies allowed by exact name only (no prefix expansion).
    // System.dll on net48 holds ISet<>, Queue<T>'s IEnumerable interfaces, Uri, Regex base types, etc.
    // Using a prefix "System" here would swallow System.Activities/System.Data/... so we match exactly.
    private static readonly string[] AllowedExactNames =
    {
        "System",
    };

    private static readonly CSharpCompilationOptions CompilationOptions = new(
        OutputKind.DynamicallyLinkedLibrary,
        optimizationLevel: OptimizationLevel.Release,
        allowUnsafe: false,
        platform: Platform.AnyCpu,
        nullableContextOptions: NullableContextOptions.Disable
    );

    private static readonly CSharpParseOptions ParseOptions = new(
        languageVersion: LanguageVersion.CSharp10,
        documentationMode: DocumentationMode.None,
        kind: SourceCodeKind.Regular
    );

    public RoslynCompiler(ILogger<RoslynCompiler> logger)
    {
        _logger = logger;

        _net8SystemRefs = LoadNet8SystemReferences();
        _net48SystemRefs = LoadNet48SystemReferences();

        var versions = LoadAllRevitVersions();
        AvailableVersions = versions;
        MissingVersions = RequiredVersions
            .Except(versions, StringComparer.Ordinal)
            .ToArray();

        if (!RequiredVersions.SequenceEqual(AllShippedVersions, StringComparer.Ordinal))
        {
            _logger.LogWarning(
                "KUKAI_COMPILE_REQUIRED_VERSIONS override active: required Revit versions = [{Required}] (full shipped matrix = [{All}]). Gate is fail-closed on this reduced set.",
                string.Join(", ", RequiredVersions), string.Join(", ", AllShippedVersions));
        }

        _logger.LogInformation(
            "RoslynCompiler initialized: {Net8Refs} net8 system refs, {Net48Refs} net48 system refs, Revit versions: [{Versions}], missing: [{MissingVersions}]",
            _net8SystemRefs.Count, _net48SystemRefs.Count, string.Join(", ", versions),
            string.Join(", ", MissingVersions));
    }

    /// <summary>
    /// Compiles the given C# code against the specified Revit version.
    /// Runs the same full Emit gate as the Bridge and returns diagnostics.
    /// </summary>
    public CompileResult Compile(string code, string revitVersion)
    {
        var sw = Stopwatch.StartNew();

        if (!_revitRefs.TryGetValue(revitVersion, out var revitApiRefs))
        {
            return new CompileResult(false, new List<CompileError>
            {
                new("REVIT_VERSION", $"Revit version '{revitVersion}' is not available. Available: {string.Join(", ", AvailableVersions)}", 0, 0)
            });
        }

        // Pick system references based on target framework
        var isNet8Target = IsNet8Target(revitVersion);
        var systemRefs = isNet8Target ? _net8SystemRefs : _net48SystemRefs;

        var allRefs = new List<MetadataReference>(systemRefs.Count + revitApiRefs.Count);
        allRefs.AddRange(systemRefs);
        allRefs.AddRange(revitApiRefs);

        var syntaxTree = CSharpSyntaxTree.ParseText(code, ParseOptions);

        var compilation = CSharpCompilation.Create(
            assemblyName: $"CompileCheck_{Guid.NewGuid():N}",
            syntaxTrees: new[] { syntaxTree },
            references: allRefs,
            options: CompilationOptions);

        using var assemblyStream = new MemoryStream();
        var emitResult = compilation.Emit(assemblyStream);
        var diagnostics = emitResult.Diagnostics;

        var errors = diagnostics
            .Where(d => d.Severity == DiagnosticSeverity.Error)
            .Select(d =>
            {
                var lineSpan = d.Location.GetLineSpan();
                var line = lineSpan.StartLinePosition.Line + 1;
                var col = lineSpan.StartLinePosition.Character + 1;
                return new CompileError(d.Id, d.GetMessage(), line, col);
            })
            .ToList();

        sw.Stop();
        _logger.LogInformation(
            "Compile revit={Version} success={Success} errors={ErrorCount} time={ElapsedMs}ms",
            revitVersion, errors.Count == 0, errors.Count, sw.ElapsedMilliseconds);

        return new CompileResult(errors.Count == 0, errors);
    }

    /// <summary>
    /// Load .NET 8 system references from TRUSTED_PLATFORM_ASSEMBLIES.
    /// Same approach as CodeCompiler.cs in the bridge.
    /// </summary>
    private List<MetadataReference> LoadNet8SystemReferences()
    {
        var refs = new List<MetadataReference>();
        var tpa = AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES") as string;
        if (string.IsNullOrEmpty(tpa))
            return refs;

        foreach (var asmPath in tpa.Split(Path.PathSeparator))
        {
            var asmName = Path.GetFileNameWithoutExtension(asmPath);
            if (!IsAllowedAssembly(asmName))
                continue;

            try
            {
                refs.Add(MetadataReference.CreateFromFile(asmPath));
            }
            catch (Exception ex)
            {
                RecordFailedReference(asmPath, "net8-system", ex);
            }
        }

        return refs;
    }

    /// <summary>
    /// Load .NET Framework 4.8 reference assemblies for Revit 2021-2024.
    /// </summary>
    private List<MetadataReference> LoadNet48SystemReferences()
    {
        var refs = new List<MetadataReference>();

        // Windows path: standard install location of .NET Framework SDK.
        var refAsmDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            "Reference Assemblies", "Microsoft", "Framework", ".NETFramework", "v4.8");

        // Linux fallback: Microsoft.NETFramework.ReferenceAssemblies.net48 NuGet package.
        if (!Directory.Exists(refAsmDir))
        {
            var nugetRefRoot = Path.Combine(
                ResolveNuGetPackagesRoot(),
                "microsoft.netframework.referenceassemblies.net48");
            if (Directory.Exists(nugetRefRoot))
            {
                refAsmDir = Path.Combine(
                    nugetRefRoot, Net48ReferenceAssemblyPackageVersion,
                    "build", ".NETFramework", "v4.8");
            }
        }

        if (!Directory.Exists(refAsmDir))
        {
            _logger.LogWarning("net48 reference assemblies not found at {Path}", refAsmDir);
            return refs;
        }

        // Load from root and Facades subdirectory
        var searchDirs = new[] { refAsmDir, Path.Combine(refAsmDir, "Facades") };

        foreach (var dir in searchDirs)
        {
            if (!Directory.Exists(dir))
                continue;

            foreach (var dll in Directory.GetFiles(dir, "*.dll"))
            {
                var asmName = Path.GetFileNameWithoutExtension(dll);
                if (!IsAllowedAssembly(asmName))
                    continue;

                try
                {
                    refs.Add(MetadataReference.CreateFromFile(dll));
                }
                catch (Exception ex)
                {
                    RecordFailedReference(dll, "net48-system", ex);
                }
            }
        }

        return refs;
    }

    /// <summary>
    /// Discover and load RevitAPI references for all available versions from NuGet cache.
    /// </summary>
    private List<string> LoadAllRevitVersions()
    {
        var versions = new List<string>();
        var nugetDir = Path.Combine(
            ResolveNuGetPackagesRoot(),
            "revit_all_main_versions_api_x64");

        if (!Directory.Exists(nugetDir))
        {
            _logger.LogWarning("RevitAPI NuGet packages not found at {Path}", nugetDir);
            return versions;
        }

        foreach (var majorVer in RequiredVersions)
        {
            var versionDir = Path.Combine(nugetDir, $"{majorVer}.0.0");
            if (!Directory.Exists(versionDir))
                continue;

            var isNet8 = IsNet8Target(majorVer);
            var libSubdir = isNet8 ? "net8.0" : "net48";
            var libDir = Path.Combine(versionDir, "lib", libSubdir);

            if (!Directory.Exists(libDir))
                continue;

            var requiredDlls = new[] { "RevitAPI.dll", "RevitAPIUI.dll" };
            var revitRefs = new List<MetadataReference>();
            var completeReferenceSet = true;
            foreach (var dllName in requiredDlls)
            {
                var dll = Path.Combine(libDir, dllName);
                if (!File.Exists(dll))
                {
                    completeReferenceSet = false;
                    _logger.LogWarning(
                        "Required {Dll} is absent for Revit {Version}",
                        dllName, majorVer);
                    continue;
                }
                try
                {
                    revitRefs.Add(MetadataReference.CreateFromFile(dll));
                    _logger.LogDebug("Loaded {Dll} for Revit {Version}", Path.GetFileName(dll), majorVer);
                }
                catch (Exception ex)
                {
                    completeReferenceSet = false;
                    _logger.LogWarning(ex, "Failed to load {Dll}", dll);
                    RecordFailedReference(dll, $"revit-api-{majorVer}", ex);
                }
            }

            if (completeReferenceSet && revitRefs.Count == requiredDlls.Length)
            {
                _revitRefs[majorVer] = revitRefs;
                versions.Add(majorVer);
            }
        }

        return versions;
    }

    /// <summary>
    /// Resolve the same global-packages folder used by NuGet restore.
    ///
    /// Respecting NUGET_PACKAGES is essential for hermetic CI and production
    /// hosts with a non-default cache.  Falling back to the user profile keeps
    /// the existing deployment layout unchanged.
    /// </summary>
    private static string ResolveNuGetPackagesRoot()
    {
        var configured = Environment.GetEnvironmentVariable("NUGET_PACKAGES");
        if (!string.IsNullOrWhiteSpace(configured))
            return Path.GetFullPath(configured);

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".nuget", "packages");
    }

    private static bool IsAllowedAssembly(string assemblyName)
    {
        if (AllowedExactNames.Any(n => assemblyName.Equals(n, StringComparison.OrdinalIgnoreCase)))
            return true;

        return AllowedPrefixes.Any(p =>
            assemblyName.StartsWith(p, StringComparison.OrdinalIgnoreCase) ||
            assemblyName.Equals(p, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// Record a failed reference load. Logs to stderr (always visible in journalctl)
    /// AND adds to the static failure list so <c>/health</c> can surface the diagnostic
    /// without requiring log file access.
    /// </summary>
    private void RecordFailedReference(string path, string category, Exception ex)
    {
        var msg = $"[CompileService] Failed to load reference '{path}' ({category}): {ex.GetType().Name}: {ex.Message}";
        Console.Error.WriteLine(msg);
        _logger.LogWarning(ex, "Failed to load reference {Path} (category {Category})", path, category);
        _failedReferences.Add(new FailedReference(path, category, $"{ex.GetType().Name}: {ex.Message}", DateTime.UtcNow));
    }

    /// <summary>
    /// Test-only hook: deliberately attempt to load a bad reference path so tests can
    /// assert that <see cref="FailedReferences"/> is populated. Returns true if the
    /// failure was recorded (i.e. the path was actually invalid).
    /// </summary>
    public bool TryLoadReferenceForDiagnostics(string path, string category)
    {
        try
        {
            MetadataReference.CreateFromFile(path);
            return false;
        }
        catch (Exception ex)
        {
            RecordFailedReference(path, category, ex);
            return true;
        }
    }
}

public record CompileResult(bool Success, List<CompileError> Errors);

public record CompileError(string Code, string Message, int Line, int Column);

/// <summary>
/// Diagnostic entry for a reference DLL that failed to load.
/// Exposed via GET /health to make silent load failures visible in prod.
/// </summary>
public record FailedReference(string Path, string Category, string Error, DateTime Timestamp);
