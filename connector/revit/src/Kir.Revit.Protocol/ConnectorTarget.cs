using System;
using System.Text.Json.Serialization;

namespace Kir.Revit.Protocol
{
    /// <summary>Persistent execution origin; never a session token or pipe address.</summary>
    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    public sealed class ConnectorTarget
    {
        [JsonPropertyName("journal_id")]
        public string JournalId { get; }
        [JsonPropertyName("instance_id")]
        public string InstanceId { get; }
        [JsonPropertyName("revit_version")]
        public string RevitVersion { get; }

        [JsonConstructor]
        public ConnectorTarget(string journalId, string instanceId, string revitVersion)
        {
            JournalId = CanonicalUuid(journalId, "journal_id");
            InstanceId = CanonicalUuid(instanceId, "instance_id");
            if (revitVersion != "2021" && revitVersion != "2022" && revitVersion != "2023"
                && revitVersion != "2024" && revitVersion != "2025" && revitVersion != "2026")
                throw new ArgumentException("unsupported Revit version", nameof(revitVersion));
            RevitVersion = revitVersion;
        }

        public bool Matches(ConnectorTarget? other) => other != null
            && JournalId == other.JournalId && InstanceId == other.InstanceId
            && RevitVersion == other.RevitVersion;

        public static string CanonicalUuid(string value, string name)
        {
            if (!Guid.TryParse(value, out var parsed) || parsed == Guid.Empty)
                throw new ArgumentException(name + " must be a nonempty UUID", name);
            return parsed.ToString("D");
        }
    }
}
