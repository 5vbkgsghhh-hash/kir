using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Kir.Revit.Connector.Compat;
using Kir.Revit.Connector.Context;
using Kir.Revit.Protocol;
#if REVIT_MODERN
using System.Runtime.Loader;
#endif

namespace Kir.Revit.Connector.Execution
{
    internal sealed class ExecutionEngine
    {
        private const int MaxChangedIds = 10000;
        private const int LegacyAssemblyLimit = 64;
        private readonly ContextSnapshotCollector _context;
        private readonly OperationJournal _journal;
#if REVIT_LEGACY
        private int _legacyAssemblyCount;
#endif

        public ExecutionEngine(ContextSnapshotCollector context, OperationJournal journal)
        {
            _context = context;
            _journal = journal;
        }

        public OperationReceipt Execute(UIApplication application, ExecutionWorkItem item)
        {
            if (_journal.Target == null || !_journal.Target.Matches(item.Input.Target))
                return Unpersisted(item, "target_mismatch", false, "work item does not target this owned execution journal");
            var existing = _journal.Get(item.OperationId);
            // Exact retry answers the original request, even with no current
            // document or a different active document. It is not a new write.
            if (existing != null) return Existing(item, existing);
            if (!item.Admission.IsOpen) return Cancelled(item, "session closed before execution admission");
            var snapshot = _context.Capture(application);
            if (snapshot.RevitVersion != item.Input.Target.RevitVersion
                || !ContextSnapshotCollector.Matches(snapshot, item.Precondition))
                return PersistTerminal(item, ReceiptStates.ContextChangedBeforeStart, false, true, "context changed before execution", null, null);

#if REVIT_LEGACY
            if (_legacyAssemblyCount >= LegacyAssemblyLimit)
                return Rejected(item, "legacy Revit session assembly limit reached; restart Revit before more generated executions");
#endif
            if (!item.Admission.TryStart(_journal, item.Input, out var raced, out var cancelled))
                return cancelled ? Cancelled(item, "session closed before durable start") : Existing(item, raced!);
            var changes = new ChangeManifest();
            var foreign = new ForeignChanges();
            var document = application.ActiveUIDocument.Document;
            // A change in a document this operation was never bound to is not an
            // event to filter out: it is evidence that the barrier was crossed,
            // and it has to reach the receipt. CaptureChanges keeps its own
            // same-document guard and its own signature.
            EventHandler<DocumentChangedEventArgs> handler = (_, args) =>
            {
                if (DocumentRevisionTracker.SameDocument(args.GetDocument(), document))
                    CaptureChanges(document, args, changes);
                else RecordForeign(args, foreign);
            };
            application.Application.DocumentChanged += handler;
            try
            {
                object? result;
#if REVIT_MODERN
                var loadContext = new AssemblyLoadContext("kir-generated-" + item.OperationId, true);
                try
                {
                    using (var stream = new System.IO.MemoryStream(item.AssemblyBytes, false))
                    {
                        var assembly = loadContext.LoadFromStream(stream);
                        result = Invoke(assembly, document, application.ActiveUIDocument);
                    }
                }
                finally { loadContext.Unload(); }
#else
                _legacyAssemblyCount++;
                result = Invoke(Assembly.Load(item.AssemblyBytes), document, application.ActiveUIDocument);
#endif
                // Loud terminal refusal, not a success with a quiet manifest.
                // The result is dropped on purpose: a run that also touched a
                // document nobody bound must not be presented as completed.
                if (foreign.Observed)
                    return PersistTerminal(item, ReceiptStates.ForeignDocumentChanged, true, false,
                        ForeignError(foreign), null, changes);
                return PersistTerminal(item, ReceiptStates.InvocationCompleted, true, false, null, SerializeResult(result), changes);
            }
            catch (Exception ex)
            {
                var actual = ex is TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
                var state = foreign.Observed ? ReceiptStates.ForeignDocumentChanged
                    : changes.IsEmpty ? ReceiptStates.FailedAfterStartUnknown : ReceiptStates.FailedAfterObservedChange;
                var error = actual.GetType().Name + ": " + actual.Message;
                if (foreign.Observed) error = ForeignError(foreign) + "; " + error;
                return PersistTerminal(item, state, true, false, error, null, changes);
            }
            finally { application.Application.DocumentChanged -= handler; }
        }

        public OperationReceipt Rejected(ExecutionWorkItem item, string error) =>
            PersistTerminal(item, ReceiptStates.RejectedBeforeStart, false, true, error, null, null);

        public OperationReceipt Cancelled(ExecutionWorkItem item, string error) =>
            PersistTerminal(item, ReceiptStates.CancelledBeforeStart, false, true, error, null, null);

        // A late compiler completion may reach a disposed scheduler after its
        // owner lease was released. It must not read/write that old authority.
        public OperationReceipt RuntimeClosed(ExecutionWorkItem item) =>
            Unpersisted(item, ReceiptStates.RunningUnknown, false,
                "runtime ownership has ended; resolve the original journal before any retry");

        public OperationReceipt FailedUnknown(ExecutionWorkItem item, Exception exception) =>
            PersistTerminal(item, ReceiptStates.FailedAfterStartUnknown, true, false, exception.Message, null, null);

        private static OperationReceipt Existing(ExecutionWorkItem item, JournalRecord existing)
        {
            if (!existing.IsBound)
                return Unpersisted(item, ReceiptStates.LegacyUnbound, false,
                    "legacy operation has no verified v4 target binding; inspect its archive and do not replay");
            if (!existing.Input!.Matches(item.Input))
                return Unpersisted(item, ReceiptStates.OperationConflict, false,
                    "operation_id was already bound to different input; the original record was not changed");
            return existing.Receipt ?? Unpersisted(item, ReceiptStates.RunningUnknown, true,
                "prior execution started without a terminal receipt; reconcile read-only and do not replay");
        }

        private static OperationReceipt Unpersisted(ExecutionWorkItem item, string state, bool started, string error) =>
            new OperationReceipt { Target = item.Input.Target, OperationId = item.OperationId, SourceSha256 = item.SourceSha256,
                DocumentKey = item.Input.DocumentKey, Precondition = item.Precondition,
                State = state, Started = started, MayRetry = false, Error = error,
                TimestampUtc = DateTime.UtcNow.ToString("O") };

        private OperationReceipt PersistTerminal(ExecutionWorkItem item, string state, bool started, bool mayRetry,
            string? error, ResultWire? result, ChangeManifest? changes)
        {
            var receipt = new OperationReceipt
            {
                Target = item.Input.Target,
                OperationId = item.OperationId,
                SourceSha256 = item.SourceSha256,
                DocumentKey = item.Precondition.DocumentKey,
                Precondition = item.Precondition,
                State = state,
                Started = started,
                MayRetry = mayRetry,
                TransactionEvidence = changes == null ? "not_observed" : changes.IsEmpty ? "changes_not_observed" : "changes_observed",
                SemanticEvidence = "unverified",
                ResultJson = result?.Json,
                ResultTruncated = result?.Truncated ?? false,
                ResultError = result?.Error,
                Error = error,
                Changes = changes,
                TimestampUtc = DateTime.UtcNow.ToString("O"),
            };
            try { return _journal.AppendTerminal(item.Input, receipt).Receipt!; }
            catch (JournalBindingException ex)
            {
                return Unpersisted(item, ex.Status, ex.Status == ReceiptStates.RunningUnknown,
                    "operation_id is already started or has another/unrecoverable binding; the original journal record was not changed");
            }
            catch
            {
                // A terminal state is authoritative only after journal append
                // succeeds. Preserve provisional result/change evidence, but
                // do not freeze a client ledger on an unpersisted terminal.
                // A later lookup may return the actual durable terminal (or a
                // valid no-start tombstone when admission never happened).
                receipt.State = ReceiptStates.RunningUnknown;
                receipt.Started = true; // a previous admission of this ID may have started
                // Without a healthy durable authority, another admission of
                // this ID may already have started. Never grant replay here.
                receipt.MayRetry = false;
                receipt.Error = "terminal receipt could not be durably journaled";
            }
            return receipt;
        }

        private static object? Invoke(Assembly assembly, Document document, UIDocument uiDocument)
        {
            var type = assembly.GetType("Kir.Generated.UserCode", true, false)!;
            var method = type.GetMethod("Execute", BindingFlags.Public | BindingFlags.Static)
                         ?? throw new MissingMethodException("Kir.Generated.UserCode.Execute not found");
            return method.Invoke(null, new object[] { document, uiDocument });
        }

        private sealed class ResultWire
        {
            public string? Json { get; set; }
            public bool Truncated { get; set; }
            public string? Error { get; set; }
        }

        private static ResultWire SerializeResult(object? result)
        {
            try
            {
                var json = JsonSerializer.Serialize(result);
                if (Encoding.UTF8.GetByteCount(json) > ProtocolConstants.MaxResultJsonBytes)
                    return new ResultWire
                    {
                        Truncated = true,
                        Error = "execution result exceeds the connector result limit",
                    };
                return new ResultWire { Json = json };
            }
            catch (Exception ex)
            {
                return new ResultWire
                {
                    Error = "execution result could not be serialized: " + ex.GetType().Name,
                };
            }
        }

        private sealed class ForeignChanges
        {
            public bool Observed;
            public List<string> TransactionNames { get; } = new List<string>();
        }

        private static void RecordForeign(DocumentChangedEventArgs args, ForeignChanges foreign)
        {
            foreign.Observed = true;
            foreach (var name in args.GetTransactionNames().Take(8))
                if (!foreign.TransactionNames.Contains(name)) foreign.TransactionNames.Add(name);
        }

        private static string ForeignError(ForeignChanges foreign) =>
            "a document other than the bound document was changed during this operation"
            + (foreign.TransactionNames.Count == 0 ? string.Empty
                : "; foreign transactions: " + string.Join(", ", foreign.TransactionNames));

        private static void CaptureChanges(Document expected, DocumentChangedEventArgs args, ChangeManifest target)
        {
            if (!DocumentRevisionTracker.SameDocument(args.GetDocument(), expected)) return;
            AddIds(target.Added, args.GetAddedElementIds(), target);
            AddIds(target.Modified, args.GetModifiedElementIds(), target);
            AddIds(target.Deleted, args.GetDeletedElementIds(), target);
            foreach (var name in args.GetTransactionNames().Take(128)) target.TransactionNames.Add(name);
        }

        private static void AddIds(List<long> destination, ICollection<ElementId> ids, ChangeManifest target)
        {
            foreach (var id in ids)
            {
                if (destination.Count >= MaxChangedIds) { target.Truncated = true; break; }
                destination.Add(RevitCompat.IdValue(id));
            }
        }
    }
}
