using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Kir.Revit.Protocol
{
    public static class ProtocolConstants
    {
        public const string Version = "kir-revit-connector/4";
        public const int MaxFrameBytes = 16 * 1024 * 1024;
        public const int MaxSourceChars = 6 * 1024 * 1024;
        // Dedicated Connector -> CompilerHost profile, not the external pipe.
        // A UTF-16 unit needs at most six JSON bytes (including astral pairs).
        public const int MaxCompilerReferencePaths = 256;
        public const int MaxCompilerReferencePathChars = 32768;
        public const int MaxCompilerReferenceJsonBytes = 1024 * 1024;
        public const int MaxCompilerEnvelopeBytes = 4096;
        public const int MaxCompilerRequestFrameBytes = 6 * MaxSourceChars
            + MaxCompilerReferenceJsonBytes + MaxCompilerEnvelopeBytes;
        public const int MaxResultJsonBytes = 6 * 1024 * 1024;
    }

    public static class RequestKinds
    {
        public const string Ping = "ping";
        public const string Context = "context";
        public const string Execute = "execute";
        public const string Receipt = "receipt";
        public const string RecoverReceipt = "recover_receipt";
        public const string CancelBeforeStart = "cancel_before_start";

        public static bool IsKnown(string kind) => kind == Ping || kind == Context || kind == Execute
            || kind == Receipt || kind == RecoverReceipt || kind == CancelBeforeStart;

        // New cancel requests have one exact binding-only wire shape. Keep
        // historical kinds unchanged; neither source nor recovery_target is
        // meaningful here, including explicit null-valued properties.
        public static void ValidateCancellationPayload(JsonElement value)
        {
            if (value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("kind", out var kind)
                || kind.ValueKind != JsonValueKind.String || kind.GetString() != CancelBeforeStart) return;
            var expected = new HashSet<string>(new[] { "protocol", "request_id", "target", "session_id", "token",
                "kind", "timeout_ms", "operation_id", "source_sha256", "precondition" }, StringComparer.Ordinal);
            foreach (var property in value.EnumerateObject())
                if (!expected.Remove(property.Name)) throw new InvalidDataException("cancel_before_start has unsupported fields");
            if (expected.Count != 0 || !value.TryGetProperty("precondition", out var condition)
                || condition.ValueKind != JsonValueKind.Object)
                throw new InvalidDataException("cancel_before_start requires its complete input binding");
            expected = new HashSet<string>(new[] { "document_key", "revision", "active_view_id", "selection_digest" }, StringComparer.Ordinal);
            foreach (var property in condition.EnumerateObject())
                if (!expected.Remove(property.Name)) throw new InvalidDataException("cancel precondition has unsupported fields");
            if (expected.Count != 0) throw new InvalidDataException("cancel precondition is incomplete");
        }
    }

    public static class ReceiptStates
    {
        public const string RejectedBeforeStart = "rejected_before_start";
        public const string ContextChangedBeforeStart = "context_changed_before_start";
        public const string CancelledBeforeStart = "cancelled_before_start";
        public const string InvocationCompleted = "invocation_completed";
        public const string FailedAfterObservedChange = "failed_after_observed_change";
        // A document the operation was never bound to was changed while it ran.
        // Never retryable: the foreign edit is already in that document's undo
        // stack, and this runtime owns no transaction there to roll back.
        public const string ForeignDocumentChanged = "foreign_document_changed";
        public const string FailedAfterStartUnknown = "failed_after_start_unknown";
        public const string RunningUnknown = "running_unknown";
        public const string OperationConflict = "operation_conflict";
        public const string LegacyUnbound = "legacy_unbound";
    }

    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    public sealed class ConnectorRequest
    {
        [JsonPropertyName("target")]
        public ConnectorTarget? Target { get; set; }
        [JsonPropertyName("session_id")]
        public string SessionId { get; set; } = string.Empty;
        [JsonPropertyName("recovery_target")]
        public ConnectorTarget? RecoveryTarget { get; set; }
        [JsonPropertyName("protocol")]
        public string Protocol { get; set; } = string.Empty;

        [JsonPropertyName("request_id")]
        public string RequestId { get; set; } = string.Empty;

        [JsonPropertyName("token")]
        public string Token { get; set; } = string.Empty;

        [JsonPropertyName("kind")]
        public string Kind { get; set; } = string.Empty;

        [JsonPropertyName("operation_id")]
        public string? OperationId { get; set; }

        [JsonPropertyName("source")]
        public string? Source { get; set; }

        [JsonPropertyName("source_sha256")]
        public string? SourceSha256 { get; set; }

        [JsonPropertyName("precondition")]
        public ContextPrecondition? Precondition { get; set; }

        [JsonPropertyName("timeout_ms")]
        public int TimeoutMs { get; set; } = 120000;
    }

    public sealed class ConnectorResponse
    {
        [JsonPropertyName("target")]
        public ConnectorTarget? Target { get; set; }
        [JsonPropertyName("session_id")]
        public string SessionId { get; set; } = string.Empty;
        [JsonPropertyName("protocol")]
        public string Protocol { get; set; } = ProtocolConstants.Version;

        [JsonPropertyName("request_id")]
        public string RequestId { get; set; } = string.Empty;

        [JsonPropertyName("ok")]
        public bool Ok { get; set; }

        [JsonPropertyName("status")]
        public string Status { get; set; } = string.Empty;

        [JsonPropertyName("error")]
        public string? Error { get; set; }

        [JsonPropertyName("context")]
        public ContextSnapshot? Context { get; set; }

        [JsonPropertyName("receipt")]
        public OperationReceipt? Receipt { get; set; }

        public static ConnectorResponse Failure(string requestId, string status, string error)
        {
            return new ConnectorResponse
            {
                RequestId = requestId ?? string.Empty,
                Ok = false,
                Status = status,
                Error = error,
            };
        }
    }

    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    public sealed class ContextPrecondition
    {
        [JsonPropertyName("document_key")]
        public string DocumentKey { get; set; } = string.Empty;

        [JsonPropertyName("revision")]
        public long? Revision { get; set; }

        [JsonPropertyName("active_view_id")]
        public long? ActiveViewId { get; set; }

        [JsonPropertyName("selection_digest")]
        public string? SelectionDigest { get; set; }
    }

    /// <summary>
    /// Immutable identity of one execution request. The mutable wire DTO is
    /// copied before compilation/enqueue. Null UI conditions remain null;
    /// changing any supplied condition creates a different input.
    /// </summary>
    public sealed class OperationInputBinding
    {
        public ConnectorTarget Target { get; }
        public string OperationId { get; }
        public string SourceSha256 { get; }
        public string DocumentKey { get; }
        public long Revision { get; }
        public long? ActiveViewId { get; }
        public string? SelectionDigest { get; }

        [JsonConstructor]
        public OperationInputBinding(string operationId, string sourceSha256, string documentKey,
            long revision, long? activeViewId, string? selectionDigest, ConnectorTarget target)
        {
            Target = target ?? throw new ArgumentNullException(nameof(target));
            OperationId = NormalizeOperationId(operationId);
            if (sourceSha256 == null || sourceSha256.Length != 64
                || !IsHex(sourceSha256)) throw new ArgumentException("source_sha256 must be 64 hexadecimal characters");
            if (string.IsNullOrWhiteSpace(documentKey)) throw new ArgumentException("document_key is required");
            if (revision < 0) throw new ArgumentException("revision must be non-negative");
            SourceSha256 = sourceSha256.ToLowerInvariant();
            DocumentKey = documentKey;
            Revision = revision;
            ActiveViewId = activeViewId;
            SelectionDigest = selectionDigest;
        }

        public static OperationInputBinding Capture(string operationId, string sourceSha256, ContextPrecondition precondition, ConnectorTarget target)
        {
            if (precondition == null || !precondition.Revision.HasValue)
                throw new ArgumentException("context precondition with revision is required");
            return new OperationInputBinding(operationId, sourceSha256, precondition.DocumentKey,
                precondition.Revision.Value, precondition.ActiveViewId, precondition.SelectionDigest, target);
        }

        public ContextPrecondition ToPrecondition() => new ContextPrecondition
        {
            DocumentKey = DocumentKey, Revision = Revision,
            ActiveViewId = ActiveViewId, SelectionDigest = SelectionDigest,
        };

        public bool Matches(OperationInputBinding other) => other != null
            && Target.Matches(other.Target)
            && string.Equals(OperationId, other.OperationId, StringComparison.Ordinal)
            && string.Equals(SourceSha256, other.SourceSha256, StringComparison.Ordinal)
            && string.Equals(DocumentKey, other.DocumentKey, StringComparison.Ordinal)
            && Revision == other.Revision && ActiveViewId == other.ActiveViewId
            && string.Equals(SelectionDigest, other.SelectionDigest, StringComparison.Ordinal);

        public static string NormalizeOperationId(string value)
        {
            if (!Guid.TryParse(value, out var parsed)) throw new ArgumentException("operation_id must be a UUID");
            return parsed.ToString("D");
        }

        private static bool IsHex(string value)
        {
            foreach (var character in value)
                if (!(character >= '0' && character <= '9') && !(character >= 'a' && character <= 'f')
                    && !(character >= 'A' && character <= 'F')) return false;
            return true;
        }
    }

    public sealed class ContextSnapshot
    {
        [JsonPropertyName("has_document")]
        public bool HasDocument { get; set; }

        [JsonPropertyName("document_key")]
        public string DocumentKey { get; set; } = string.Empty;

        [JsonPropertyName("document_title")]
        public string DocumentTitle { get; set; } = string.Empty;

        [JsonPropertyName("revit_version")]
        public string RevitVersion { get; set; } = string.Empty;

        [JsonPropertyName("revision")]
        public long Revision { get; set; }

        [JsonPropertyName("active_view_id")]
        public long ActiveViewId { get; set; }

        [JsonPropertyName("selection_digest")]
        public string SelectionDigest { get; set; } = string.Empty;

        [JsonPropertyName("selection_count")]
        public int SelectionCount { get; set; }

        [JsonPropertyName("is_family_document")]
        public bool IsFamilyDocument { get; set; }

        [JsonPropertyName("is_read_only")]
        public bool IsReadOnly { get; set; }

        [JsonPropertyName("is_modifiable")]
        public bool IsModifiable { get; set; }

        [JsonPropertyName("complete")]
        public bool Complete { get; set; }
    }

    public sealed class ChangeManifest
    {
        [JsonPropertyName("added")]
        public List<long> Added { get; set; } = new List<long>();

        [JsonPropertyName("modified")]
        public List<long> Modified { get; set; } = new List<long>();

        [JsonPropertyName("deleted")]
        public List<long> Deleted { get; set; } = new List<long>();

        [JsonPropertyName("transaction_names")]
        public List<string> TransactionNames { get; set; } = new List<string>();

        [JsonPropertyName("truncated")]
        public bool Truncated { get; set; }

        [JsonIgnore]
        public bool IsEmpty => Added.Count == 0 && Modified.Count == 0 && Deleted.Count == 0;
    }

    public sealed class OperationReceipt
    {
        [JsonPropertyName("target")]
        public ConnectorTarget? Target { get; set; }
        [JsonPropertyName("operation_id")]
        public string OperationId { get; set; } = string.Empty;

        [JsonPropertyName("source_sha256")]
        public string SourceSha256 { get; set; } = string.Empty;

        [JsonPropertyName("document_key")]
        public string DocumentKey { get; set; } = string.Empty;

        [JsonPropertyName("precondition")]
        public ContextPrecondition? Precondition { get; set; }

        [JsonPropertyName("state")]
        public string State { get; set; } = string.Empty;

        [JsonPropertyName("started")]
        public bool Started { get; set; }

        [JsonPropertyName("may_retry")]
        public bool MayRetry { get; set; }

        [JsonPropertyName("transaction_evidence")]
        public string TransactionEvidence { get; set; } = "not_observed";

        [JsonPropertyName("semantic_evidence")]
        public string SemanticEvidence { get; set; } = "unverified";

        [JsonPropertyName("result_json")]
        public string? ResultJson { get; set; }

        [JsonPropertyName("result_truncated")]
        public bool ResultTruncated { get; set; }

        [JsonPropertyName("result_error")]
        public string? ResultError { get; set; }

        [JsonPropertyName("error")]
        public string? Error { get; set; }

        [JsonPropertyName("changes")]
        public ChangeManifest? Changes { get; set; }

        [JsonPropertyName("timestamp_utc")]
        public string TimestampUtc { get; set; } = string.Empty;
    }

    public sealed class CompilerRequest
    {
        [JsonPropertyName("protocol")]
        public string Protocol { get; set; } = ProtocolConstants.Version;

        [JsonPropertyName("source")]
        public string Source { get; set; } = string.Empty;

        [JsonPropertyName("reference_paths")]
        public List<string> ReferencePaths { get; set; } = new List<string>();
    }

    public sealed class CompilerResponse
    {
        [JsonPropertyName("ok")]
        public bool Ok { get; set; }

        [JsonPropertyName("assembly_base64")]
        public string? AssemblyBase64 { get; set; }

        [JsonPropertyName("diagnostics")]
        public List<string> Diagnostics { get; set; } = new List<string>();
    }

    public sealed class DiscoveryRecord
    {
        [JsonPropertyName("target")]
        public ConnectorTarget? Target { get; set; }
        [JsonPropertyName("session_id")]
        public string SessionId { get; set; } = string.Empty;
        [JsonPropertyName("protocol")]
        public string Protocol { get; set; } = ProtocolConstants.Version;

        [JsonPropertyName("pipe_name")]
        public string PipeName { get; set; } = string.Empty;

        [JsonPropertyName("token")]
        public string Token { get; set; } = string.Empty;

        [JsonPropertyName("process_id")]
        public int ProcessId { get; set; }

        [JsonPropertyName("expires_utc")]
        public string ExpiresUtc { get; set; } = string.Empty;
    }
}
