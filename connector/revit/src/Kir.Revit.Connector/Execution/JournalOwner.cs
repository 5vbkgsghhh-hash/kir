using System;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class JournalOwnershipException : IOException
    {
        public string Status { get; }
        public JournalOwnershipException(string status, string message, Exception? inner = null)
            : base(message, inner) { Status = status; }
    }

    /// <summary>
    /// One OS-exclusive lease per durable journal, not per user. The lease file
    /// is never unlinked. This does not defend against an owner of the same OS
    /// account replacing files, nor promise arbitrary filesystem power-loss safety.
    /// </summary>
    internal sealed class JournalOwner : IDisposable
    {
        private readonly object _gate = new object();
        private readonly FileStream _lease;
        private bool _disposed;
        public ConnectorTarget Target { get; }
        public OperationJournal Journal { get; }

        private JournalOwner(ConnectorTarget target, FileStream lease, string path)
        {
            Target = target;
            _lease = lease;
            Journal = new OperationJournal(path, Append, target);
            if (!Journal.IsHealthy) throw new JournalOwnershipException("journal_unavailable", "new journal is not healthy");
        }

        public static JournalOwner CreateNew(string root, ConnectorTarget target)
        {
            var directory = DirectoryFor(root, target);
            if (Directory.Exists(directory) || File.Exists(directory))
                throw new JournalOwnershipException("journal_exists", "journal identity already has a pathname; it will not be adopted");
            FileStream? lease = null;
            try
            {
                Directory.CreateDirectory(directory);
                // CreateNew arbitrates simultaneous creators even if both
                // passed Directory.Exists. Neither truncates another's files.
                lease = new FileStream(Path.Combine(directory, "owner.lock"), FileMode.CreateNew,
                    FileAccess.ReadWrite, FileShare.None);
                WriteNew(Path.Combine(directory, "owner.json"), JsonSerializer.SerializeToUtf8Bytes(
                    new JournalOwnerMetadata { SchemaVersion = 1, Target = target }));
                WriteNew(Path.Combine(directory, "operations.jsonl"), Array.Empty<byte>());
                return new JournalOwner(target, lease, Path.Combine(directory, "operations.jsonl"));
            }
            catch (Exception error)
            {
                lease?.Dispose();
                // Retain incomplete directories; do not guess which file a
                // failed/racing initializer owns, truncate, or auto-adopt them.
                throw new JournalOwnershipException("journal_initialization_failed", "journal initialization failed; existing bytes were not replaced", error);
            }
        }

        public static JournalRecovery OpenRecovery(string root, ConnectorTarget expected)
        {
            var directory = DirectoryFor(root, expected);
            var lockPath = Path.Combine(directory, "owner.lock");
            var metadataPath = Path.Combine(directory, "owner.json");
            var journalPath = Path.Combine(directory, "operations.jsonl");
            if (!File.Exists(lockPath) || !File.Exists(metadataPath) || !File.Exists(journalPath))
                throw new JournalOwnershipException("journal_unavailable", "original journal ownership files are missing; absence is not replay permission");
            FileStream lease;
            try { lease = new FileStream(lockPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None); }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
            {
                throw new JournalOwnershipException("journal_lease_unavailable", "original journal lease cannot be acquired; it may still have a live owner", error);
            }
            try
            {
                var metadata = ReadMetadata(metadataPath);
                if (!expected.Matches(metadata.Target))
                    throw new JournalOwnershipException("journal_target_mismatch", "original journal metadata does not match the requested execution target");
                // Reuse the real strict parser and detached Get; recovery
                // exposes neither append nor TryStart to its caller.
                var journal = new OperationJournal(journalPath, expected);
                if (!journal.IsHealthy) throw new JournalOwnershipException(journal.FailureStatus, "original journal is corrupt, unbound or belongs to another target");
                return new JournalRecovery(expected, lease, journal);
            }
            catch (Exception error)
            {
                lease.Dispose();
                if (error is JournalOwnershipException) throw;
                throw new JournalOwnershipException("journal_unavailable", "original journal ownership metadata is corrupt or unavailable", error);
            }
        }

        private static string DirectoryFor(string root, ConnectorTarget target)
        {
            if (target == null) throw new ArgumentNullException(nameof(target));
            if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("journal root is required", nameof(root));
            // IDs are validated before paths. No wire-supplied absolute journal
            // path or implicit fallback to a global archive is accepted.
            return Path.Combine(Path.GetFullPath(root), "journals", target.JournalId);
        }

        private static JournalOwnerMetadata ReadMetadata(string path)
        {
            var file = new FileInfo(path);
            if (file.Length <= 0 || file.Length > 16384) throw new InvalidDataException("invalid owner metadata size");
            var bytes = File.ReadAllBytes(path);
            using (var document = StrictJson.Parse(bytes))
            {
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("schema_version", out var schema)
                    || schema.ValueKind != JsonValueKind.Number || schema.GetInt32() != 1
                    || !root.TryGetProperty("target", out _)) throw new InvalidDataException("unsupported owner metadata schema");
            }
            var metadata = JsonSerializer.Deserialize<JournalOwnerMetadata>(bytes);
            if (metadata?.Target == null) throw new InvalidDataException("owner target is missing");
            return metadata;
        }

        private static void WriteNew(string path, byte[] bytes)
        {
            using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read,
                       4096, FileOptions.WriteThrough))
            {
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);
            }
        }

        private void Append(string path, byte[] bytes)
        {
            lock (_gate)
            {
                if (_disposed) throw new ObjectDisposedException(nameof(JournalOwner));
                OperationJournal.AppendDurably(path, bytes);
            }
        }

        public void Dispose()
        {
            lock (_gate)
            {
                if (_disposed) return;
                _disposed = true;
                _lease.Dispose();
            }
        }
    }

    internal sealed class JournalRecovery : IDisposable
    {
        private readonly object _gate = new object();
        private readonly FileStream _lease;
        private readonly OperationJournal _journal;
        private bool _disposed;
        public ConnectorTarget Target { get; }
        internal JournalRecovery(ConnectorTarget target, FileStream lease, OperationJournal journal)
        { Target = target; _lease = lease; _journal = journal; }
        public JournalRecord? Get(string operationId)
        {
            lock (_gate)
            {
                if (_disposed) throw new ObjectDisposedException(nameof(JournalRecovery));
                return _journal.Get(operationId);
            }
        }
        public void Dispose()
        {
            lock (_gate)
            {
                if (_disposed) return;
                _disposed = true;
                _lease.Dispose();
            }
        }
    }

    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    internal sealed class JournalOwnerMetadata
    {
        [JsonPropertyName("schema_version")]
        public int SchemaVersion { get; set; }
        [JsonPropertyName("target")]
        public ConnectorTarget? Target { get; set; }
    }
}
