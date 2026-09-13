using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;

namespace Kir.Revit.Protocol
{
    /// <summary>One JSON boundary for wire frames and durable records.</summary>
    public static class StrictJson
    {
        private static readonly Encoding Utf8 = new UTF8Encoding(false, true);

        public static JsonDocument Parse(byte[] utf8)
        {
            if (utf8 == null) throw new ArgumentNullException(nameof(utf8));
            // JsonDocument defers decoding some string values. Validate every
            // byte now, not only whichever properties a consumer happens to read.
            Utf8.GetCharCount(utf8);
            return Checked(JsonDocument.Parse(utf8));
        }

        public static JsonDocument Parse(string json) => Checked(JsonDocument.Parse(json));

        private static JsonDocument Checked(JsonDocument document)
        {
            try { CheckDuplicateKeys(document.RootElement); return document; }
            catch { document.Dispose(); throw; }
        }

        public static IEnumerable<string> ReadUtf8Lines(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var reader = new StreamReader(stream, Utf8, detectEncodingFromByteOrderMarks: false))
            {
                string? line;
                while ((line = reader.ReadLine()) != null) yield return line;
            }
        }

        public static void CheckDuplicateKeys(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Object)
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in value.EnumerateObject())
                {
                    // Property.Name is decoded, so "kind" and "\u006bind"
                    // are the same key rather than two spellings to resolve.
                    if (!names.Add(property.Name)) throw new InvalidDataException("duplicate JSON key");
                    CheckDuplicateKeys(property.Value);
                }
            }
            else if (value.ValueKind == JsonValueKind.Array)
                foreach (var item in value.EnumerateArray()) CheckDuplicateKeys(item);
        }
    }
}
