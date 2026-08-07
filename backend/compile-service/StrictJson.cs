using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace CompileService;

/// <summary>
/// Exact-shape JSON primitives shared by the packaged compiler contract and the
/// strict compile-receipt wire protocol.
/// </summary>
internal static class StrictJson
{
    private static readonly UTF8Encoding StrictUtf8 = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    internal static readonly JsonSerializerOptions SerializerOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    internal static Dictionary<string, JsonElement> Object(
        JsonElement value,
        string path,
        params string[] expectedFields)
    {
        if (value.ValueKind != JsonValueKind.Object)
            throw new JsonContractException($"{path} must be an object");

        var fields = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
        {
            if (!fields.TryAdd(property.Name, property.Value))
            {
                throw new JsonContractException(
                    $"{path} contains duplicate field '{property.Name}'");
            }
        }

        var expected = new HashSet<string>(expectedFields, StringComparer.Ordinal);
        var missing = expected.Except(fields.Keys, StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();
        var extra = fields.Keys.Except(expected, StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();
        if (missing.Length > 0 || extra.Length > 0)
        {
            throw new JsonContractException(
                $"{path} fields mismatch: missing=[{string.Join(", ", missing)}], " +
                $"extra=[{string.Join(", ", extra)}]");
        }

        return fields;
    }

    internal static string String(JsonElement value, string path)
    {
        if (value.ValueKind != JsonValueKind.String)
            throw new JsonContractException($"{path} must be a string");
        var result = value.GetString();
        if (string.IsNullOrEmpty(result))
            throw new JsonContractException($"{path} must be a non-empty string");
        return result;
    }

    internal static bool Boolean(JsonElement value, string path)
    {
        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => throw new JsonContractException($"{path} must be boolean"),
        };
    }

    internal static long PositiveInteger(JsonElement value, string path)
    {
        if (value.ValueKind != JsonValueKind.Number ||
            !value.TryGetInt64(out var result) || result <= 0)
        {
            throw new JsonContractException(
                $"{path} must be a positive integer");
        }
        return result;
    }

    internal static IReadOnlyList<string> StringArray(
        JsonElement value,
        string path)
    {
        if (value.ValueKind != JsonValueKind.Array)
            throw new JsonContractException($"{path} must be an array of strings");

        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var index = 0;
        foreach (var item in value.EnumerateArray())
        {
            var text = String(item, $"{path}[{index}]");
            if (!seen.Add(text))
                throw new JsonContractException($"{path} contains duplicates");
            result.Add(text);
            index++;
        }
        if (result.Count == 0)
            throw new JsonContractException($"{path} must not be empty");
        return result;
    }

    internal static string Sha256Hex(ReadOnlySpan<byte> value) =>
        Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant();

    internal static string Sha256Hex(string value) =>
        Sha256Hex(Utf8Bytes(value));

    internal static byte[] Utf8Bytes(string value)
    {
        try
        {
            return StrictUtf8.GetBytes(value);
        }
        catch (EncoderFallbackException exception)
        {
            throw new JsonContractException(
                "string contains an invalid Unicode surrogate", exception);
        }
    }

    internal static string CanonicalDigest(object value)
    {
        var element = JsonSerializer.SerializeToElement(
            value,
            SerializerOptions);
        return CanonicalDigest(element);
    }

    internal static string CanonicalDigest(JsonElement value) =>
        Sha256Hex(CanonicalBytes(value));

    internal static byte[] CanonicalBytes(JsonElement value)
    {
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            Indented = false,
        }))
        {
            WriteCanonical(writer, value);
        }
        return stream.ToArray();
    }

    private static void WriteCanonical(Utf8JsonWriter writer, JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var property in value.EnumerateObject()
                    .OrderBy(item => item.Name, StringComparer.Ordinal))
                {
                    writer.WritePropertyName(property.Name);
                    WriteCanonical(writer, property.Value);
                }
                writer.WriteEndObject();
                break;
            case JsonValueKind.Array:
                writer.WriteStartArray();
                foreach (var item in value.EnumerateArray())
                    WriteCanonical(writer, item);
                writer.WriteEndArray();
                break;
            case JsonValueKind.String:
                writer.WriteStringValue(value.GetString());
                break;
            case JsonValueKind.Number:
                // Contract numbers are integers. Preserve their validated JSON
                // token so no floating-point conversion can alter evidence.
                writer.WriteRawValue(value.GetRawText(), skipInputValidation: false);
                break;
            case JsonValueKind.True:
                writer.WriteBooleanValue(true);
                break;
            case JsonValueKind.False:
                writer.WriteBooleanValue(false);
                break;
            case JsonValueKind.Null:
                writer.WriteNullValue();
                break;
            default:
                throw new JsonContractException(
                    $"unsupported JSON token {value.ValueKind}");
        }
    }
}

internal sealed class JsonContractException : Exception
{
    internal JsonContractException(string message)
        : base(message)
    {
    }

    internal JsonContractException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
