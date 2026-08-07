using System.Reflection;
using System.Text.Json;

namespace CompileService;

internal enum TargetFrameworkKind
{
    Net48,
    Net8,
}

internal sealed record CompilerPolicy(
    string RoslynPackageVersion,
    string LanguageVersion,
    string Optimization,
    string Platform,
    bool AllowUnsafe,
    string Nullable);

internal sealed record ReferencePolicy(
    IReadOnlyList<string> SystemPrefixes,
    IReadOnlyList<string> SystemExactNames,
    IReadOnlyList<string> RevitAssemblies);

internal sealed record TargetProfile(
    string ProfileId,
    string RevitYear,
    string ReleasePolicy,
    string TargetFramework,
    TargetFrameworkKind FrameworkKind,
    string RevitApiPackageVersion,
    string RevitApiReferencePath,
    string ProfileDigest);

/// <summary>
/// Validated view of the same packaged target_profiles.v1.json consumed by
/// kukai.compiler_contract. Digests use Python's sorted-key, compact UTF-8 JSON
/// contract rather than the source file's formatting.
/// </summary>
public sealed class TargetProfileManifest
{
    internal const string ManifestSchema = "target-profile-manifest/1";
    internal const string ProfileSchema = "target-profile/1";
    internal const string RelativePath = "compiler_contracts/target_profiles.v1.json";

    private static readonly HashSet<string> OfficialYears = new(
        new[] { "2023", "2024", "2025", "2026" },
        StringComparer.Ordinal);
    private static readonly HashSet<string> FrozenYears = new(
        new[] { "2021", "2022" },
        StringComparer.Ordinal);

    private readonly IReadOnlyDictionary<string, TargetProfile> _profilesByYear;

    private TargetProfileManifest(
        CompilerPolicy compilerPolicy,
        ReferencePolicy referencePolicy,
        IReadOnlyList<TargetProfile> profiles,
        string manifestDigest)
    {
        CompilerPolicy = compilerPolicy;
        ReferencePolicy = referencePolicy;
        Profiles = profiles;
        ManifestDigest = manifestDigest;
        _profilesByYear = profiles.ToDictionary(
            profile => profile.RevitYear,
            StringComparer.Ordinal);
    }

    internal CompilerPolicy CompilerPolicy { get; }
    internal ReferencePolicy ReferencePolicy { get; }
    internal IReadOnlyList<TargetProfile> Profiles { get; }
    internal string ManifestDigest { get; }

    internal TargetProfile ProfileForYear(string revitYear)
    {
        if (!_profilesByYear.TryGetValue(revitYear, out var profile))
        {
            throw new JsonContractException(
                $"target profile for Revit '{revitYear}' is unavailable");
        }
        return profile;
    }

    internal static TargetProfileManifest LoadPackaged()
    {
        var path = Path.Combine(
            AppContext.BaseDirectory,
            "compiler_contracts",
            "target_profiles.v1.json");
        try
        {
            return Load(path);
        }
        catch (Exception exception) when (
            exception is IOException or JsonException or JsonContractException)
        {
            throw new InvalidOperationException(
                $"Packaged compiler target manifest is invalid: {path}",
                exception);
        }
    }

    internal static TargetProfileManifest Load(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(path), new JsonDocumentOptions
        {
            AllowTrailingCommas = false,
            CommentHandling = JsonCommentHandling.Disallow,
            MaxDepth = 32,
        });
        var root = StrictJson.Object(
            document.RootElement,
            "manifest",
            "schema_version",
            "compiler_policy",
            "reference_policy",
            "profiles");

        var schema = StrictJson.String(root["schema_version"], "schema_version");
        if (!string.Equals(schema, ManifestSchema, StringComparison.Ordinal))
            throw new JsonContractException($"unsupported manifest schema '{schema}'");

        var compilerPolicy = ParseCompilerPolicy(root["compiler_policy"]);
        var referencePolicy = ParseReferencePolicy(root["reference_policy"]);
        var profiles = ParseProfiles(
            root["profiles"],
            root["compiler_policy"],
            root["reference_policy"]);

        return new TargetProfileManifest(
            compilerPolicy,
            referencePolicy,
            profiles,
            StrictJson.CanonicalDigest(document.RootElement));
    }

    private static CompilerPolicy ParseCompilerPolicy(JsonElement value)
    {
        var fields = StrictJson.Object(
            value,
            "compiler_policy",
            "roslyn_package_version",
            "language_version",
            "optimization",
            "platform",
            "allow_unsafe",
            "nullable");
        var roslyn = StrictJson.String(
            fields["roslyn_package_version"],
            "compiler_policy.roslyn_package_version");
        var language = StrictJson.String(
            fields["language_version"],
            "compiler_policy.language_version");
        var optimization = StrictJson.String(
            fields["optimization"],
            "compiler_policy.optimization");
        var platform = StrictJson.String(
            fields["platform"],
            "compiler_policy.platform");
        var allowUnsafe = StrictJson.Boolean(
            fields["allow_unsafe"],
            "compiler_policy.allow_unsafe");
        var nullable = StrictJson.String(
            fields["nullable"],
            "compiler_policy.nullable");

        var configuredRoslyn = Assembly.GetExecutingAssembly()
            .GetCustomAttributes<AssemblyMetadataAttribute>()
            .SingleOrDefault(attribute => string.Equals(
                attribute.Key,
                "RoslynPackageVersion",
                StringComparison.Ordinal))
            ?.Value;
        if (string.IsNullOrEmpty(configuredRoslyn) ||
            !string.Equals(roslyn, configuredRoslyn, StringComparison.Ordinal))
        {
            throw new JsonContractException(
                "manifest Roslyn version disagrees with CompileService build metadata");
        }
        if (language != "10.0" || optimization != "release" ||
            platform != "AnyCPU" || allowUnsafe || nullable != "disabled")
        {
            throw new JsonContractException(
                "compiler policy must be C# 10, Release, AnyCPU, " +
                "unsafe disabled, nullable disabled");
        }

        return new CompilerPolicy(
            roslyn,
            language,
            optimization,
            platform,
            allowUnsafe,
            nullable);
    }

    private static ReferencePolicy ParseReferencePolicy(JsonElement value)
    {
        var fields = StrictJson.Object(
            value,
            "reference_policy",
            "system_prefixes",
            "system_exact_names",
            "revit_assemblies");
        var prefixes = StrictJson.StringArray(
            fields["system_prefixes"],
            "reference_policy.system_prefixes");
        var exactNames = StrictJson.StringArray(
            fields["system_exact_names"],
            "reference_policy.system_exact_names");
        var revitAssemblies = StrictJson.StringArray(
            fields["revit_assemblies"],
            "reference_policy.revit_assemblies");
        if (prefixes.Intersect(exactNames, StringComparer.Ordinal).Any())
        {
            throw new JsonContractException(
                "system prefix and exact-name policies overlap");
        }
        if (!revitAssemblies.SequenceEqual(
            new[] { "RevitAPI", "RevitAPIUI" },
            StringComparer.Ordinal))
        {
            throw new JsonContractException(
                "revit_assemblies must be exactly RevitAPI and RevitAPIUI");
        }
        return new ReferencePolicy(prefixes, exactNames, revitAssemblies);
    }

    private static IReadOnlyList<TargetProfile> ParseProfiles(
        JsonElement value,
        JsonElement compilerPolicy,
        JsonElement referencePolicy)
    {
        if (value.ValueKind != JsonValueKind.Array)
            throw new JsonContractException("profiles must be an array");

        var profiles = new List<TargetProfile>();
        var index = 0;
        foreach (var item in value.EnumerateArray())
        {
            profiles.Add(ParseProfile(
                item,
                compilerPolicy,
                referencePolicy,
                index));
            index++;
        }
        if (profiles.Count == 0)
            throw new JsonContractException("profiles must not be empty");

        var ids = profiles.Select(profile => profile.ProfileId).ToArray();
        var years = profiles.Select(profile => profile.RevitYear).ToArray();
        if (ids.Distinct(StringComparer.Ordinal).Count() != ids.Length)
            throw new JsonContractException("profile_id values must be unique");
        if (years.Distinct(StringComparer.Ordinal).Count() != years.Length)
            throw new JsonContractException("Revit profile years must be unique");
        if (!years.SequenceEqual(
            years.OrderBy(year => year, StringComparer.Ordinal),
            StringComparer.Ordinal))
        {
            throw new JsonContractException(
                "profiles must be ordered by Revit year");
        }

        var official = profiles
            .Where(profile => profile.ReleasePolicy == "official")
            .Select(profile => profile.RevitYear)
            .ToHashSet(StringComparer.Ordinal);
        var frozen = profiles
            .Where(profile => profile.ReleasePolicy == "frozen")
            .Select(profile => profile.RevitYear)
            .ToHashSet(StringComparer.Ordinal);
        if (!official.SetEquals(OfficialYears) || !frozen.SetEquals(FrozenYears))
        {
            throw new JsonContractException(
                "release policy must be official=2023..2026 and frozen=2021..2022");
        }
        return profiles;
    }

    private static TargetProfile ParseProfile(
        JsonElement value,
        JsonElement compilerPolicy,
        JsonElement referencePolicy,
        int index)
    {
        var path = $"profiles[{index}]";
        var fields = StrictJson.Object(
            value,
            path,
            "profile_id",
            "revit_year",
            "release_policy",
            "target_framework",
            "revit_api_package_version",
            "revit_api_reference_path");
        var profileId = StrictJson.String(fields["profile_id"], $"{path}.profile_id");
        var year = StrictJson.String(fields["revit_year"], $"{path}.revit_year");
        var release = StrictJson.String(
            fields["release_policy"],
            $"{path}.release_policy");
        var framework = StrictJson.String(
            fields["target_framework"],
            $"{path}.target_framework");
        var packageVersion = StrictJson.String(
            fields["revit_api_package_version"],
            $"{path}.revit_api_package_version");
        var referencePath = StrictJson.String(
            fields["revit_api_reference_path"],
            $"{path}.revit_api_reference_path");

        if (year.Length != 4 || !year.All(char.IsAsciiDigit) ||
            !int.TryParse(year, out var numericYear) || numericYear < 2000)
        {
            throw new JsonContractException($"{path}.revit_year is invalid");
        }
        if (release is not ("official" or "frozen"))
            throw new JsonContractException($"{path}.release_policy is unsupported");

        var expectedFramework = numericYear >= 2025 ? "net8.0" : "net48";
        var frameworkKind = expectedFramework == "net8.0"
            ? TargetFrameworkKind.Net8
            : TargetFrameworkKind.Net48;
        if (!string.Equals(framework, expectedFramework, StringComparison.Ordinal))
        {
            throw new JsonContractException(
                $"{path}: Revit {year} must target {expectedFramework}");
        }
        var frameworkToken = frameworkKind == TargetFrameworkKind.Net8
            ? "net8"
            : "net48";
        var expectedId = $"revit-{year}-{frameworkToken}-cs10-r1";
        if (!string.Equals(profileId, expectedId, StringComparison.Ordinal))
            throw new JsonContractException($"{path}.profile_id must be '{expectedId}'");
        if (!string.Equals(packageVersion, $"{year}.0.0", StringComparison.Ordinal))
        {
            throw new JsonContractException(
                $"{path}.revit_api_package_version must match the Revit year");
        }
        if (!string.Equals(referencePath, $"lib/{framework}", StringComparison.Ordinal))
        {
            throw new JsonContractException(
                $"{path}.revit_api_reference_path does not match target framework");
        }

        var digestMaterial = new Dictionary<string, object?>
        {
            ["schema_version"] = ProfileSchema,
            ["compiler_policy"] = compilerPolicy,
            ["reference_policy"] = referencePolicy,
            ["profile"] = value,
        };
        return new TargetProfile(
            profileId,
            year,
            release,
            framework,
            frameworkKind,
            packageVersion,
            referencePath,
            StrictJson.CanonicalDigest(digestMaterial));
    }
}
