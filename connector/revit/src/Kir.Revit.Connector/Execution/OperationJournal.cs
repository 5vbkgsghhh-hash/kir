using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class OperationJournal
    {
        private readonly object _gate = new object();
        private readonly string _path;
        private readonly Action<string, byte[]> _appendDurably;
        private readonly Dictionary<string, JournalRecord> _latest = new Dictionary<string, JournalRecord>(StringComparer.Ordinal);
        private bool _healthy = true;
        public ConnectorTarget? Target { get; }
        public string FailureStatus { get; private set; } = "journal_unavailable";

        // A targetless open is an archival reader, never an execution writer.
        public OperationJournal(string path, ConnectorTarget? target = null) : this(path, AppendDurably, target) { }

        // Narrow deterministic I/O-failure seam: tests write a partial real
        // record then throw. This is not a second storage implementation.
        internal OperationJournal(string path, Action<string, byte[]> appendDurably, ConnectorTarget? target = null)
        {
            Target = target;
            _path = path;
            _appendDurably = appendDurably ?? throw new ArgumentNullException(nameof(appendDurably));
            try
            {
                if (target != null)
                    Directory.CreateDirectory(Path.GetDirectoryName(path) ?? throw new InvalidOperationException("journal directory missing"));
                else if (!File.Exists(path)) throw new FileNotFoundException("archival journal is missing", path);
                if (File.Exists(path))
                {
                    // A syntactically complete JSON tail is still incomplete
                    // without its record delimiter. Otherwise the next append
                    // silently joins two objects into one unrecoverable line.
                    using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                    {
                        if (stream.Length > 0)
                        {
                            stream.Seek(-1, SeekOrigin.End);
                            if (stream.ReadByte() != '\n') throw new InvalidDataException("unterminated journal record");
                        }
                    }
                    foreach (var line in StrictJson.ReadUtf8Lines(path).Where(line => !string.IsNullOrWhiteSpace(line)))
                    {
                        var record = ParseRecord(line);
                        ValidateOwner(record);
                        _latest.TryGetValue(record.OperationId, out var prior);
                        ValidateTransition(prior, record);
                        _latest[record.OperationId] = record;
                    }
                }
            }
            catch (JournalBindingException error) { _healthy = false; FailureStatus = error.Status; }
            catch { _healthy = false; }
        }

        public JournalRecord? Get(string operationId)
        {
            var key = OperationInputBinding.NormalizeOperationId(operationId);
            lock (_gate)
            {
                EnsureHealthy();
                return _latest.TryGetValue(key, out var record) ? Clone(record) : null;
            }
        }

        public bool IsHealthy
        {
            get { lock (_gate) return _healthy; }
        }

        public OperationReceipt? GetReceipt(string operationId)
        {
            var record = Get(operationId);
            return record != null && record.IsBound ? record.Receipt : null;
        }

        public bool TryStart(OperationInputBinding input, out JournalRecord? existing)
        {
            lock (_gate)
            {
                EnsureHealthy();
                RequireWriter(input);
                if (_latest.TryGetValue(input.OperationId, out var prior))
                {
                    existing = Clone(prior);
                    return false;
                }
                Persist(JournalRecord.Create(input, "started", null));
                existing = null;
                return true;
            }
        }

        public JournalRecord AppendTerminal(OperationInputBinding input, OperationReceipt receipt)
        {
            var record = ParseRecord(JsonSerializer.Serialize(JournalRecord.Create(input, "terminal", receipt)));
            lock (_gate)
            {
                EnsureHealthy();
                RequireWriter(input);
                _latest.TryGetValue(input.OperationId, out var prior);
                if (prior != null)
                {
                    if (!prior.IsBound) throw new JournalBindingException(ReceiptStates.LegacyUnbound);
                    if (!prior.Input!.Matches(input)) throw new JournalBindingException(ReceiptStates.OperationConflict);
                    // The first terminal result owns this operation forever.
                    // A late queue result cannot replace it or add history.
                    if (prior.Receipt != null) return Clone(prior);
                    // A rejected duplicate queue admission cannot prove the
                    // original request did not already start.
                    if (!receipt.Started) throw new JournalBindingException(ReceiptStates.RunningUnknown);
                }
                ValidateTransition(prior, record);
                Persist(record);
                return Clone(record);
            }
        }

        private void EnsureHealthy()
        {
            if (!_healthy) throw new IOException("operation journal is unavailable");
        }

        private void RequireWriter(OperationInputBinding input)
        {
            if (Target == null) throw new JournalBindingException(ReceiptStates.LegacyUnbound);
            if (!Target.Matches(input.Target)) throw new JournalBindingException("journal_target_mismatch");
        }

        private void ValidateOwner(JournalRecord record)
        {
            if (Target == null) return; // Archive inspection cannot confer v4 write authority.
            if (!record.IsBound) throw new JournalBindingException(ReceiptStates.LegacyUnbound);
            if (!Target.Matches(record.Input!.Target)) throw new JournalBindingException("journal_target_mismatch");
        }

        private void Persist(JournalRecord record)
        {
            var detached = Clone(record);
            var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(detached) + Environment.NewLine);
            try
            {
                _appendDurably(_path, bytes);
                _latest[detached.OperationId] = detached;
            }
            catch
            {
                // The filesystem may contain a prefix or even a whole record.
                // The in-memory index must never remain a healthy authority.
                _healthy = false;
                throw;
            }
        }

        internal static void AppendDurably(string path, byte[] bytes)
        {
            using (var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read, 4096, FileOptions.WriteThrough))
            {
                stream.Write(bytes, 0, bytes.Length);
                stream.Flush(true);
            }
        }

        private static JournalRecord Clone(JournalRecord record) => ParseRecord(JsonSerializer.Serialize(record));

        private static JournalRecord ParseRecord(string line)
        {
            using (var document = StrictJson.Parse(line))
            {
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object) throw new InvalidDataException("journal record must be an object");
                var version = root.TryGetProperty("SchemaVersion", out var field) ? field.GetInt32() : 0;
                if (version != 0 && version != 3 && version != JournalRecord.CurrentSchemaVersion)
                    throw new InvalidDataException("unsupported journal schema");
                if (version != JournalRecord.CurrentSchemaVersion)
                {
                    // Do not deserialize a v3 Input through the new constructor
                    // or manufacture a target for a legacy record.
                    return new JournalRecord { SchemaVersion = version,
                        OperationId = OperationInputBinding.NormalizeOperationId(root.GetProperty("OperationId").GetString()!),
                        SourceSha256 = root.TryGetProperty("SourceSha256", out var hash) ? hash.GetString() ?? "" : "",
                        DocumentKey = root.TryGetProperty("DocumentKey", out var documentKey) ? documentKey.GetString() ?? "" : "",
                        Phase = root.TryGetProperty("Phase", out var phase) ? phase.GetString() ?? "" : "",
                        TimestampUtc = root.TryGetProperty("TimestampUtc", out var time) ? time.GetString() ?? "" : "",
                        ArchiveJson = root.TryGetProperty("ArchiveJson", out var archive) && archive.ValueKind == JsonValueKind.String ? archive.GetString() : line };
                }
                if (version == JournalRecord.CurrentSchemaVersion)
                {
                    var input = root.GetProperty("Input");
                    var required = new HashSet<string>(new[] { "Target", "OperationId", "SourceSha256", "DocumentKey", "Revision", "ActiveViewId", "SelectionDigest" }, StringComparer.Ordinal);
                    foreach (var property in input.EnumerateObject())
                        if (!required.Remove(property.Name)) throw new InvalidDataException("unsupported input binding field");
                    if (required.Count != 0) throw new InvalidDataException("incomplete input binding");
                }
                var record = JsonSerializer.Deserialize<JournalRecord>(line) ?? throw new InvalidDataException("null journal record");
                record.OperationId = OperationInputBinding.NormalizeOperationId(record.OperationId);
                if (record.Input == null || record.OperationId != record.Input.OperationId
                    || record.SourceSha256 != record.Input.SourceSha256 || record.DocumentKey != record.Input.DocumentKey)
                    throw new InvalidDataException("journal input identity mismatch");
                if (record.Phase == "started")
                {
                    if (record.Receipt != null) throw new InvalidDataException("started record contains a terminal receipt");
                }
                else if (record.Phase == "terminal")
                {
                    var receipt = record.Receipt ?? throw new InvalidDataException("terminal receipt missing");
                    var observed = OperationInputBinding.Capture(receipt.OperationId, receipt.SourceSha256,
                        receipt.Precondition ?? throw new InvalidDataException("receipt precondition missing"),
                        receipt.Target ?? throw new InvalidDataException("receipt target missing"));
                    if (!record.Input.Matches(observed) || receipt.DocumentKey != record.DocumentKey)
                        throw new InvalidDataException("receipt input identity mismatch");
                    // 🔴 A SECOND CARRIER OF THE STATE LIST. It lives here, not in
                    // `Messages.cs`, and so it was missed by both reviews: the journal did not
                    // recognize the engine's new terminal state and, on
                    // reading, threw «contradictory receipt state», which caused
                    // a loud refusal to degrade into running_unknown. This was found by the
                    // headless `ContextLifecycle.Tests` rig, not by reading the code.
                    var stateStarted = receipt.State == ReceiptStates.InvocationCompleted
                        || receipt.State == ReceiptStates.FailedAfterObservedChange
                        || receipt.State == ReceiptStates.ForeignDocumentChanged
                        || receipt.State == ReceiptStates.FailedAfterStartUnknown || receipt.State == ReceiptStates.RunningUnknown;
                    var stateNotStarted = receipt.State == ReceiptStates.RejectedBeforeStart
                        || receipt.State == ReceiptStates.ContextChangedBeforeStart || receipt.State == ReceiptStates.CancelledBeforeStart;
                    if ((!stateStarted && !stateNotStarted) || receipt.Started != stateStarted || (receipt.Started && receipt.MayRetry))
                        throw new InvalidDataException("contradictory receipt state");
                }
                else throw new InvalidDataException("unknown journal phase");
                return record;
            }
        }

        private static void ValidateTransition(JournalRecord? prior, JournalRecord current)
        {
            if (!current.IsBound)
            {
                if (prior != null && prior.IsBound) throw new InvalidDataException("legacy record cannot replace a bound v4 input");
                return;
            }
            if (prior != null)
            {
                if (!prior.IsBound || !prior.Input!.Matches(current.Input!) || prior.Phase != "started"
                    || current.Phase != "terminal" || current.Receipt?.Started != true)
                    throw new InvalidDataException("invalid journal transition or input rebinding");
            }
            else if (current.Phase == "terminal" && current.Receipt!.Started)
                throw new InvalidDataException("started receipt has no durable start record");
        }

        // Compatibility alias: one policy lives in Protocol for every reader.
        internal static void CheckDuplicateKeys(JsonElement value) => StrictJson.CheckDuplicateKeys(value);
    }

    internal sealed class JournalRecord
    {
        public const int CurrentSchemaVersion = 4;
        // Deliberately zero by default: legacy data must not acquire v4 status
        // just because a deserializer ran a new constructor.
        public int SchemaVersion { get; set; }
        public OperationInputBinding? Input { get; set; }
        public string? ArchiveJson { get; set; }
        public string OperationId { get; set; } = string.Empty;
        public string SourceSha256 { get; set; } = string.Empty;
        public string DocumentKey { get; set; } = string.Empty;
        public string Phase { get; set; } = string.Empty;
        public OperationReceipt? Receipt { get; set; }
        public string TimestampUtc { get; set; } = string.Empty;

        [JsonIgnore]
        public bool IsBound => SchemaVersion == CurrentSchemaVersion && Input != null;

        public static JournalRecord Create(OperationInputBinding input, string phase, OperationReceipt? receipt) =>
            new JournalRecord { SchemaVersion = CurrentSchemaVersion, Input = input,
                OperationId = input.OperationId, SourceSha256 = input.SourceSha256, DocumentKey = input.DocumentKey,
                Phase = phase, Receipt = receipt, TimestampUtc = DateTime.UtcNow.ToString("O") };
    }

    internal sealed class JournalBindingException : InvalidOperationException
    {
        public string Status { get; }
        public JournalBindingException(string status) : base(status) { Status = status; }
    }
}
