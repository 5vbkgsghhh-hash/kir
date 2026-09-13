using System;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class SessionAdmission
    {
        private readonly object _gate = new object();
        private readonly Func<DateTime> _utcNow;
        private bool _closed;
        public string SessionId { get; }
        public DateTime ExpiresUtc { get; }

        public SessionAdmission(string sessionId, DateTime expiresUtc)
            : this(sessionId, expiresUtc, () => DateTime.UtcNow) { }

        internal SessionAdmission(string sessionId, DateTime expiresUtc, Func<DateTime> utcNow)
        {
            SessionId = ConnectorTarget.CanonicalUuid(sessionId, "session_id");
            _utcNow = utcNow ?? throw new ArgumentNullException(nameof(utcNow));
            if (expiresUtc.Kind != DateTimeKind.Utc || expiresUtc <= _utcNow())
                throw new ArgumentException("session expiry must be a future UTC instant", nameof(expiresUtc));
            ExpiresUtc = expiresUtc;
        }

        public bool IsOpen { get { lock (_gate) return !_closed && _utcNow() < ExpiresUtc; } }
        public void Close() { lock (_gate) _closed = true; }

        // This lock is the linearization boundary: closing the session cannot
        // slip between granting admission and durably claiming the start.
        internal bool TryStart(OperationJournal journal, OperationInputBinding input,
            out JournalRecord? prior, out bool cancelled)
        {
            lock (_gate)
            {
                prior = null;
                cancelled = _closed || _utcNow() >= ExpiresUtc;
                return !cancelled && journal.TryStart(input, out prior);
            }
        }

        internal bool TryCancelBeforeStart(OperationJournal journal, OperationInputBinding input,
            out JournalRecord? result)
        {
            lock (_gate)
            {
                result = null;
                if (_closed || _utcNow() >= ExpiresUtc) return false;
                // AppendTerminal competes atomically with every TryStart,
                // including another session's already queued work. It keeps
                // the original terminal, or refuses a started/different input.
                result = journal.AppendTerminal(input, new OperationReceipt
                {
                    Target = input.Target, OperationId = input.OperationId, SourceSha256 = input.SourceSha256,
                    DocumentKey = input.DocumentKey, Precondition = input.ToPrecondition(),
                    State = ReceiptStates.CancelledBeforeStart, Started = false, MayRetry = true,
                    TransactionEvidence = "not_observed", SemanticEvidence = "unverified",
                    ResultJson = null, ResultError = null, ResultTruncated = false, Changes = null,
                    Error = "explicit cancellation before durable start", TimestampUtc = DateTime.UtcNow.ToString("O"),
                });
                return true;
            }
        }
    }
}
