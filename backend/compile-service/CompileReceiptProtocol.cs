using System.Text.Json;
using System.Text.Json.Serialization;

namespace CompileService;

internal sealed record ArtifactBinding(
    [property: JsonPropertyName("schema"), JsonPropertyOrder(0)] string Schema,
    [property: JsonPropertyName("lower_digest"), JsonPropertyOrder(1)] string LowerDigest,
    [property: JsonPropertyName("target_profile_digest"), JsonPropertyOrder(2)] string TargetProfileDigest,
    [property: JsonPropertyName("emitter_contract"), JsonPropertyOrder(3)] string EmitterContract,
    [property: JsonPropertyName("source_encoding"), JsonPropertyOrder(4)] string SourceEncoding,
    [property: JsonPropertyName("source_sha256"), JsonPropertyOrder(5)] string SourceSha256,
    [property: JsonPropertyName("source_bytes"), JsonPropertyOrder(6)] long SourceBytes,
    [property: JsonPropertyName("artifact_digest"), JsonPropertyOrder(7)] string ArtifactDigest)
{
    internal Dictionary<string, object?> UnsignedEvidence() => new()
    {
        ["schema"] = Schema,
        ["lower_digest"] = LowerDigest,
        ["target_profile_digest"] = TargetProfileDigest,
        ["emitter_contract"] = EmitterContract,
        ["source_encoding"] = SourceEncoding,
        ["source_sha256"] = SourceSha256,
        ["source_bytes"] = SourceBytes,
    };
}

internal sealed record CompileUnitBinding(
    [property: JsonPropertyName("wrapper_contract"), JsonPropertyOrder(0)] string WrapperContract,
    [property: JsonPropertyName("source_encoding"), JsonPropertyOrder(1)] string SourceEncoding,
    [property: JsonPropertyName("source_sha256"), JsonPropertyOrder(2)] string SourceSha256,
    [property: JsonPropertyName("source_bytes"), JsonPropertyOrder(3)] long SourceBytes);

internal sealed record TargetBinding(
    [property: JsonPropertyName("profile_id"), JsonPropertyOrder(0)] string ProfileId,
    [property: JsonPropertyName("revit_year"), JsonPropertyOrder(1)] string RevitYear,
    [property: JsonPropertyName("profile_digest"), JsonPropertyOrder(2)] string ProfileDigest,
    [property: JsonPropertyName("manifest_digest"), JsonPropertyOrder(3)] string ManifestDigest);

internal sealed record CompileReceiptEvidence(
    [property: JsonPropertyName("schema"), JsonPropertyOrder(0)] string Schema,
    [property: JsonPropertyName("artifact"), JsonPropertyOrder(1)] ArtifactBinding Artifact,
    [property: JsonPropertyName("compile_unit"), JsonPropertyOrder(2)] CompileUnitBinding CompileUnit,
    [property: JsonPropertyName("target"), JsonPropertyOrder(3)] TargetBinding Target,
    [property: JsonPropertyName("compiler_contract"), JsonPropertyOrder(4)] string CompilerContract,
    [property: JsonPropertyName("receipt_digest"), JsonPropertyOrder(5)] string ReceiptDigest);

internal sealed record ValidatedCompileRequest(
    string Source,
    string WrappedSource,
    ArtifactBinding Artifact,
    CompileUnitBinding CompileUnit,
    TargetBinding Target,
    TargetProfile TargetProfile);

internal static class CompileReceiptProtocol
{
    internal const string RequestSchema = "kir-compile-request/1";
    internal const string ResponseSchema = "kir-compile-response/1";
    internal const string ReceiptSchema = "kir-compile-receipt/1";
    internal const string ArtifactSchema = "kir-emitted-artifact/1";
    internal const string EmitterContract = "kukai-authoring-csharp/1";
    internal const string CompilerContract = "roslyn-full-emit/1";

    internal static ValidatedCompileRequest Validate(
        JsonElement value,
        TargetProfileManifest manifest)
    {
        var root = StrictJson.Object(
            value,
            "request",
            "schema",
            "source",
            "artifact",
            "compile_unit",
            "target");
        var schema = StrictJson.String(root["schema"], "request.schema");
        if (!string.Equals(schema, RequestSchema, StringComparison.Ordinal))
        {
            throw new CompileProtocolException(
                "REQUEST_SCHEMA",
                $"unsupported compile request schema '{schema}'");
        }

        var source = StrictJson.String(root["source"], "request.source");
        var artifact = ParseArtifact(root["artifact"]);
        var compileUnit = ParseCompileUnit(root["compile_unit"]);
        var target = ParseTarget(root["target"]);

        ValidateArtifactSource(source, artifact);
        ValidateTarget(artifact, target, manifest, out var profile);
        var wrappedSource = ValidateCompileUnit(source, compileUnit);

        return new ValidatedCompileRequest(
            source,
            wrappedSource,
            artifact,
            compileUnit,
            target,
            profile);
    }

    internal static CompileReceiptEvidence MintReceipt(
        ValidatedCompileRequest request)
    {
        var unsigned = new Dictionary<string, object?>
        {
            ["schema"] = ReceiptSchema,
            ["artifact"] = request.Artifact,
            ["compile_unit"] = request.CompileUnit,
            ["target"] = request.Target,
            ["compiler_contract"] = CompilerContract,
        };
        return new CompileReceiptEvidence(
            ReceiptSchema,
            request.Artifact,
            request.CompileUnit,
            request.Target,
            CompilerContract,
            StrictJson.CanonicalDigest(unsigned));
    }

    private static ArtifactBinding ParseArtifact(JsonElement value)
    {
        var fields = StrictJson.Object(
            value,
            "artifact",
            "schema",
            "lower_digest",
            "target_profile_digest",
            "emitter_contract",
            "source_encoding",
            "source_sha256",
            "source_bytes",
            "artifact_digest");
        var artifact = new ArtifactBinding(
            StrictJson.String(fields["schema"], "artifact.schema"),
            Sha256(fields["lower_digest"], "artifact.lower_digest"),
            Sha256(
                fields["target_profile_digest"],
                "artifact.target_profile_digest"),
            StrictJson.String(
                fields["emitter_contract"],
                "artifact.emitter_contract"),
            StrictJson.String(
                fields["source_encoding"],
                "artifact.source_encoding"),
            Sha256(fields["source_sha256"], "artifact.source_sha256"),
            StrictJson.PositiveInteger(
                fields["source_bytes"],
                "artifact.source_bytes"),
            Sha256(fields["artifact_digest"], "artifact.artifact_digest"));

        if (artifact.Schema != ArtifactSchema)
        {
            throw new CompileProtocolException(
                "ARTIFACT_SCHEMA",
                $"unsupported emitted artifact schema '{artifact.Schema}'");
        }
        if (artifact.EmitterContract != EmitterContract)
        {
            throw new CompileProtocolException(
                "EMITTER_CONTRACT",
                $"unsupported authoring emitter contract '{artifact.EmitterContract}'");
        }
        if (artifact.SourceEncoding != "utf-8")
        {
            throw new CompileProtocolException(
                "SOURCE_ENCODING",
                "artifact source encoding must be utf-8");
        }

        var computedDigest = StrictJson.CanonicalDigest(
            artifact.UnsignedEvidence());
        if (!string.Equals(
            artifact.ArtifactDigest,
            computedDigest,
            StringComparison.Ordinal))
        {
            throw new CompileProtocolException(
                "ARTIFACT_DIGEST",
                "artifact_digest disagrees with canonical artifact binding");
        }
        return artifact;
    }

    private static CompileUnitBinding ParseCompileUnit(JsonElement value)
    {
        var fields = StrictJson.Object(
            value,
            "compile_unit",
            "wrapper_contract",
            "source_encoding",
            "source_sha256",
            "source_bytes");
        var result = new CompileUnitBinding(
            StrictJson.String(
                fields["wrapper_contract"],
                "compile_unit.wrapper_contract"),
            StrictJson.String(
                fields["source_encoding"],
                "compile_unit.source_encoding"),
            Sha256(
                fields["source_sha256"],
                "compile_unit.source_sha256"),
            StrictJson.PositiveInteger(
                fields["source_bytes"],
                "compile_unit.source_bytes"));
        if (result.WrapperContract != ExecuteWrapper.Contract)
        {
            throw new CompileProtocolException(
                "WRAPPER_CONTRACT",
                $"unsupported execute wrapper contract '{result.WrapperContract}'");
        }
        if (result.SourceEncoding != "utf-8")
        {
            throw new CompileProtocolException(
                "SOURCE_ENCODING",
                "compile-unit source encoding must be utf-8");
        }
        return result;
    }

    private static TargetBinding ParseTarget(JsonElement value)
    {
        var fields = StrictJson.Object(
            value,
            "target",
            "profile_id",
            "revit_year",
            "profile_digest",
            "manifest_digest");
        return new TargetBinding(
            StrictJson.String(fields["profile_id"], "target.profile_id"),
            StrictJson.String(fields["revit_year"], "target.revit_year"),
            Sha256(fields["profile_digest"], "target.profile_digest"),
            Sha256(fields["manifest_digest"], "target.manifest_digest"));
    }

    private static void ValidateArtifactSource(
        string source,
        ArtifactBinding artifact)
    {
        var sourceBytes = StrictJson.Utf8Bytes(source);
        if (sourceBytes.LongLength != artifact.SourceBytes ||
            !string.Equals(
                StrictJson.Sha256Hex(sourceBytes),
                artifact.SourceSha256,
                StringComparison.Ordinal))
        {
            throw new CompileProtocolException(
                "ARTIFACT_SOURCE",
                "source bytes do not match emitted artifact binding");
        }
    }

    private static void ValidateTarget(
        ArtifactBinding artifact,
        TargetBinding target,
        TargetProfileManifest manifest,
        out TargetProfile profile)
    {
        try
        {
            profile = manifest.ProfileForYear(target.RevitYear);
        }
        catch (JsonContractException exception)
        {
            throw new CompileProtocolException("TARGET_PROFILE", exception.Message);
        }
        if (target.ProfileId != profile.ProfileId ||
            target.ProfileDigest != profile.ProfileDigest ||
            target.ManifestDigest != manifest.ManifestDigest)
        {
            throw new CompileProtocolException(
                "TARGET_BINDING",
                "target disagrees with packaged compiler contract");
        }
        if (artifact.TargetProfileDigest != target.ProfileDigest)
        {
            throw new CompileProtocolException(
                "TARGET_BINDING",
                "artifact and target profile digests disagree");
        }
    }

    private static string ValidateCompileUnit(
        string source,
        CompileUnitBinding compileUnit)
    {
        var wrappedSource = ExecuteWrapper.Wrap(source);
        var wrappedBytes = StrictJson.Utf8Bytes(wrappedSource);
        if (wrappedBytes.LongLength != compileUnit.SourceBytes ||
            !string.Equals(
                StrictJson.Sha256Hex(wrappedBytes),
                compileUnit.SourceSha256,
                StringComparison.Ordinal))
        {
            throw new CompileProtocolException(
                "COMPILE_UNIT",
                "wrapped source bytes do not match compile-unit binding");
        }
        return wrappedSource;
    }

    private static string Sha256(JsonElement value, string path)
    {
        var result = StrictJson.String(value, path);
        if (result.Length != 64 || result.Any(character =>
            !((character >= '0' && character <= '9') ||
                (character >= 'a' && character <= 'f'))))
        {
            throw new JsonContractException(
                $"{path} must be lowercase SHA-256");
        }
        return result;
    }
}

internal sealed class CompileProtocolException : Exception
{
    internal CompileProtocolException(string code, string message)
        : base(message)
    {
        Code = code;
    }

    internal string Code { get; }
}
