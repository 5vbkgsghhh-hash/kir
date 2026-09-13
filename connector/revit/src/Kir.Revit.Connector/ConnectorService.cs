using System;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector
{
    internal sealed class ConnectorService
    {
        private readonly string _token;
        public SessionAdmission Admission { get; }
        public ConnectorTarget Target => _target;
        internal bool HasToken(string token) => TokenEquals(token, _token);
        private readonly ContextQueryScheduler _context;
        private readonly ExternalEventScheduler _execution;
        private readonly CompilerHostClient _compiler;
        private readonly OperationJournal _journal;
        private readonly ConnectorTarget _target;
        private readonly string _sessionId;
        private readonly string _journalRoot;

        public ConnectorService(string token, SessionAdmission admission, ContextQueryScheduler context,
            ExternalEventScheduler execution, CompilerHostClient compiler, OperationJournal journal,
            ConnectorTarget target, string journalRoot)
        {
            if (string.IsNullOrWhiteSpace(token)) throw new ArgumentException("session token is required", nameof(token));
            Admission = admission ?? throw new ArgumentNullException(nameof(admission));
            _target = target ?? throw new ArgumentNullException(nameof(target));
            if (!target.Matches(journal.Target)) throw new ArgumentException("service target must match owned journal");
            _sessionId = admission.SessionId;
            _journalRoot = journalRoot;
            _token = token;
            _context = context;
            _execution = execution;
            _compiler = compiler;
            _journal = journal;
        }

        public async Task<ConnectorResponse> Handle(ConnectorRequest request)
        {
            var response = await HandleCore(request).ConfigureAwait(false);
            response.Target = _target;
            response.SessionId = _sessionId;
            return response;
        }

        private async Task<ConnectorResponse> HandleCore(ConnectorRequest request)
        {
            if (request == null) return ConnectorResponse.Failure(string.Empty, "invalid_request", "request is null");
            if (!string.Equals(request.Protocol, ProtocolConstants.Version, StringComparison.Ordinal))
                return ConnectorResponse.Failure(request.RequestId, "protocol_mismatch", "unsupported protocol");
            if (string.IsNullOrWhiteSpace(request.RequestId))
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "request_id is required");
            if (!TokenEquals(request.Token, _token)) return ConnectorResponse.Failure(request.RequestId, "unauthorized", "invalid session token");
            if (request.Target == null) return ConnectorResponse.Failure(request.RequestId, "invalid_request", "execution route target is required");
            if (!_target.Matches(request.Target)) return ConnectorResponse.Failure(request.RequestId, "target_mismatch", "request targets a different journal, process instance or Revit version");
            string session;
            try { session = ConnectorTarget.CanonicalUuid(request.SessionId, "session_id"); }
            catch (ArgumentException error) { return ConnectorResponse.Failure(request.RequestId, "invalid_request", error.Message); }
            if (session != _sessionId) return ConnectorResponse.Failure(request.RequestId, "session_mismatch", "request targets a different transport session");

            if ((request.Kind == RequestKinds.Ping || request.Kind == RequestKinds.Context) && !Admission.IsOpen)
                return ConnectorResponse.Failure(request.RequestId, "disabled", "connector session is closed or expired");
            if (request.Kind == RequestKinds.Ping) return Success(request.RequestId, "ready");
            if (request.Kind == RequestKinds.Context)
            {
                try
                {
                    var snapshot = await Timeout(_context.Capture(), Math.Min(request.TimeoutMs, 30000)).ConfigureAwait(false);
                    if (snapshot.HasDocument && snapshot.RevitVersion != _target.RevitVersion)
                        return ConnectorResponse.Failure(request.RequestId, "context_target_mismatch", "native document version differs from the owned runtime target");
                    var response = Success(request.RequestId, "context"); response.Context = snapshot; return response;
                }
                catch (Exception ex) { return ConnectorResponse.Failure(request.RequestId, "context_error", ex.Message); }
            }
            if (request.Kind == RequestKinds.Receipt)
            {
                try
                {
                    var record = _journal.Get(OperationInputBinding.NormalizeOperationId(request.OperationId!));
                    if (record == null) return ConnectorResponse.Failure(request.RequestId, "not_found",
                        "no durable record was found; a timed-out request may still be queued, so this is not permission to replay");
                    return PriorResponse(request.RequestId, record);
                }
                catch (ArgumentException ex) { return ConnectorResponse.Failure(request.RequestId, "invalid_request", ex.Message); }
                catch (Exception ex) { return ConnectorResponse.Failure(request.RequestId, "journal_unavailable", ex.Message); }
            }
            if (request.Kind == RequestKinds.RecoverReceipt)
            {
                if (request.RecoveryTarget == null) return ConnectorResponse.Failure(request.RequestId, "invalid_request", "original recovery_target is required");
                try
                {
                    var operationId = OperationInputBinding.NormalizeOperationId(request.OperationId!);
                    JournalRecord? record;
                    if (_target.Matches(request.RecoveryTarget)) record = _journal.Get(operationId);
                    else
                    {
                        using (var recovery = JournalOwner.OpenRecovery(_journalRoot, request.RecoveryTarget))
                            record = recovery.Get(operationId);
                    }
                    return record == null ? ConnectorResponse.Failure(request.RequestId, "not_found_unconfirmed",
                        "original journal has no durable record; this does not authorize a mutation retry") : PriorResponse(request.RequestId, record);
                }
                catch (ArgumentException error) { return ConnectorResponse.Failure(request.RequestId, "invalid_request", error.Message); }
                catch (JournalOwnershipException error) { return ConnectorResponse.Failure(request.RequestId, error.Status, error.Message); }
                catch (Exception error) { return ConnectorResponse.Failure(request.RequestId, "journal_unavailable", error.Message); }
            }
            if (request.Kind == RequestKinds.CancelBeforeStart) return CancelBeforeStart(request);
            if (request.Kind != RequestKinds.Execute)
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "unknown request kind");
            if (!_journal.IsHealthy)
                return ConnectorResponse.Failure(request.RequestId, "journal_unavailable", "writes are disabled until the durable operation journal is available");
            return await Execute(request).ConfigureAwait(false);
        }

        private ConnectorResponse CancelBeforeStart(ConnectorRequest request)
        {
            // Source-free exact-input tombstone, not a document operation and
            // never writable recovery of another process's journal.
            if (request.Source != null || request.RecoveryTarget != null
                || request.TimeoutMs < 1000 || request.TimeoutMs > 300000)
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "cancel requires only its exact input binding and valid deadline");
            OperationInputBinding input;
            try { input = OperationInputBinding.Capture(request.OperationId!, request.SourceSha256!, request.Precondition!, _target); }
            catch (ArgumentException) { return ConnectorResponse.Failure(request.RequestId, "invalid_request", "cancel input binding is incomplete or invalid"); }
            try
            {
                var prior = _journal.Get(input.OperationId);
                if (prior != null)
                {
                    if (prior.IsBound && !prior.Input!.Matches(input))
                        return ConnectorResponse.Failure(request.RequestId, "operation_conflict", "operation_id is already bound to different input");
                    return PriorResponse(request.RequestId, prior);
                }
                if (!Admission.TryCancelBeforeStart(_journal, input, out var terminal))
                    return ConnectorResponse.Failure(request.RequestId, "disabled", "session closed before cancellation admission");
                return PriorResponse(request.RequestId, terminal!);
            }
            catch (JournalBindingException error)
            {
                // A TryStart that won the race must stay unknown/noncancelled.
                return ConnectorResponse.Failure(request.RequestId, error.Status,
                    "operation already started or has another/unrecoverable binding; journal was not replaced");
            }
            catch (Exception)
            {
                // Append may have reached disk before failing. Neither absence
                // nor I/O failure proves the operation was cancelled.
                return ConnectorResponse.Failure(request.RequestId, "journal_unavailable",
                    "cancellation could not be confirmed by the owned durable journal");
            }
        }

        private async Task<ConnectorResponse> Execute(ConnectorRequest request)
        {
            if (string.IsNullOrWhiteSpace(request.OperationId) || !Guid.TryParse(request.OperationId, out _))
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "operation_id must be a UUID");
            if (request.Source == null || string.IsNullOrWhiteSpace(request.Source)
                || request.Source.Length > ProtocolConstants.MaxSourceChars)
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "source is missing or too large");
            var source = request.Source!;
            var sourceHash = Sha256(source);
            if (!string.Equals(sourceHash, request.SourceSha256, StringComparison.OrdinalIgnoreCase))
                return ConnectorResponse.Failure(request.RequestId, "invalid_request", "source_sha256 mismatch");
            OperationInputBinding input;
            try { input = OperationInputBinding.Capture(request.OperationId!, sourceHash, request.Precondition!, _target); }
            catch (ArgumentException ex) { return ConnectorResponse.Failure(request.RequestId, "invalid_request", ex.Message); }

            JournalRecord? prior;
            try { prior = _journal.Get(input.OperationId); }
            catch (Exception ex) { return ConnectorResponse.Failure(request.RequestId, "journal_unavailable", ex.Message); }
            if (prior != null)
            {
                if (!prior.IsBound) return PriorResponse(request.RequestId, prior);
                if (!prior.Input!.Matches(input))
                    return ConnectorResponse.Failure(request.RequestId, "operation_conflict", "operation_id was already bound to different input");
                return PriorResponse(request.RequestId, prior);
            }
            if (!Admission.IsOpen) return ConnectorResponse.Failure(request.RequestId, "disabled", "session is closed; no new execution was admitted");
            var compiled = _compiler.Compile(source, request.TimeoutMs);
            if (!compiled.Ok || string.IsNullOrWhiteSpace(compiled.AssemblyBase64))
                return ConnectorResponse.Failure(request.RequestId, "compile_rejected", string.Join("\n", compiled.Diagnostics.Take(100)));
            byte[] bytes;
            try { bytes = Convert.FromBase64String(compiled.AssemblyBase64); }
            catch { return ConnectorResponse.Failure(request.RequestId, "compile_error", "compiler returned invalid assembly bytes"); }

            var work = new ExecutionWorkItem(input, bytes, Admission);
            try
            {
                var receipt = await Timeout(_execution.Enqueue(work), Math.Max(1000, Math.Min(request.TimeoutMs, 300000))).ConfigureAwait(false);
                var response = Success(request.RequestId, "receipt"); response.Receipt = receipt; return response;
            }
            catch (TimeoutException)
            {
                return ConnectorResponse.Failure(request.RequestId, ReceiptStates.RunningUnknown,
                    "execution deadline elapsed; query the receipt and do not replay the mutation");
            }
        }

        private static ConnectorResponse PriorResponse(string requestId, JournalRecord record)
        {
            if (!record.IsBound) return ConnectorResponse.Failure(requestId, ReceiptStates.LegacyUnbound,
                "legacy operation is retained as archive but has no verified v4 target binding; do not replay");
            if (record.Receipt != null)
            {
                var complete = Success(requestId, "receipt"); complete.Receipt = record.Receipt; return complete;
            }
            var response = ConnectorResponse.Failure(requestId, ReceiptStates.RunningUnknown,
                "operation started without a terminal receipt; reconcile read-only and do not replay");
            response.Receipt = new OperationReceipt
            {
                Target = record.Input!.Target,
                OperationId = record.OperationId, SourceSha256 = record.SourceSha256, DocumentKey = record.DocumentKey,
                Precondition = record.Input!.ToPrecondition(), State = ReceiptStates.RunningUnknown,
                Started = true, MayRetry = false, TimestampUtc = record.TimestampUtc,
            };
            return response;
        }

        private static async Task<T> Timeout<T>(Task<T> task, int timeoutMs)
        {
            var delay = Task.Delay(timeoutMs);
            var completed = await Task.WhenAny(task, delay).ConfigureAwait(false);
            if (completed != task) throw new TimeoutException();
            return await task.ConfigureAwait(false);
        }

        private static ConnectorResponse Success(string requestId, string status) =>
            new ConnectorResponse { RequestId = requestId, Ok = true, Status = status };

        private static bool TokenEquals(string supplied, string expected)
        {
            var left = Encoding.UTF8.GetBytes(supplied ?? string.Empty);
            var right = Encoding.UTF8.GetBytes(expected);
            if (left.Length != right.Length) return false;
            var difference = 0;
            for (var index = 0; index < left.Length; index++) difference |= left[index] ^ right[index];
            return difference == 0;
        }

        private static string Sha256(string value)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-", string.Empty).ToLowerInvariant();
        }
    }
}
