using System;
using System.IO;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Connector;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;

internal static class Program
{
    private static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    private static int Main(string[] args)
    {
        Require(args.Length == 1 && Directory.Exists(args[0]), "explicit existing owned artifact directory required");
        var ui = new UIApplication();
        var doc = new Document(new NativeDocument());
        ui.ActiveUIDocument = new UIDocument(doc);
        using var tracker = new DocumentRevisionTracker(ui.Application);
        var collector = new ContextSnapshotCollector(tracker);
        var warm = collector.Capture(ui);
        var target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2026");
        var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddHours(1));
        var condition = new ContextPrecondition { DocumentKey=warm.DocumentKey, Revision=warm.Revision,
            ActiveViewId=warm.ActiveViewId, SelectionDigest=warm.SelectionDigest };
        Console.WriteLine(JsonSerializer.Serialize(new { target, session_id=admission.SessionId, precondition=condition }));
        Console.Out.Flush();
        using var command = JsonDocument.Parse(Console.ReadLine() ?? throw new Exception("missing input binding"));
        var input = OperationInputBinding.Capture(command.RootElement.GetProperty("operation_id").GetString()!,
            command.RootElement.GetProperty("source_sha256").GetString()!, condition, target);
        var journalPath = Path.Combine(args[0], "operations.jsonl");
        var journal = new OperationJournal(journalPath, target);
        var engine = new ExecutionEngine(collector, journal);
        using var queue = new ExternalEventScheduler(engine);
        var service = new ConnectorService("fixture-token", admission, null!, null!, null!, journal, target, args[0]);

        // Same actual tracker failure path as existing CaptureFailure control.
        doc.ThrowEquals = true;
        ui.Application.Changed(new Document(doc.Native));
        doc.ThrowEquals = false;
        var captureThrew = false;
        try { collector.Capture(ui); } catch (InvalidOperationException) { captureThrew=true; }
        Require(captureThrew, "context failure precondition was not established");
        // No source invocation is claimed. One-byte assembly is a sentinel:
        // any unexpected durable start is separately detected below.
        var work = new ExecutionWorkItem(input, new byte[] { 1 }, admission);
        var waiting = queue.Enqueue(work);
        ExternalEvent.PumpAll(ui);
        var first = waiting.GetAwaiter().GetResult();
        var emptyBeforeCancel = journal.Get(input.OperationId) == null
            && (!File.Exists(journalPath) || new FileInfo(journalPath).Length == 0);
        Require(emptyBeforeCancel && journal.IsHealthy && doc.Native.Mutations==0,
            "expected actual healthy empty journal and no native fixture mutation");
        var cancellation = service.Handle(new ConnectorRequest {
            Protocol=ProtocolConstants.Version, RequestId=Guid.NewGuid().ToString("D"), Kind=RequestKinds.CancelBeforeStart,
            Target=target, SessionId=admission.SessionId, Token="fixture-token", TimeoutMs=1000,
            OperationId=input.OperationId, SourceSha256=input.SourceSha256, Precondition=input.ToPrecondition()
        }).GetAwaiter().GetResult();
        var stored = journal.Get(input.OperationId);
        Require(cancellation.Ok && cancellation.Receipt?.State==ReceiptStates.CancelledBeforeStart
            && cancellation.Receipt.Started==false && stored?.Phase=="terminal" && doc.Native.Mutations==0,
            "actual source-free cancellation did not establish durable no-start");
        // Positive control: a genuine durable start followed by an assembly
        // loading failure must REMAIN a durable FailedAfterStartUnknown receipt.
        // The sentinel is not user code; no generated-source execution is claimed.
        var healthyUi = new UIApplication();
        var healthyDoc = new Document(new NativeDocument());
        healthyUi.ActiveUIDocument = new UIDocument(healthyDoc);
        using var healthyTracker = new DocumentRevisionTracker(healthyUi.Application);
        var healthyCollector = new ContextSnapshotCollector(healthyTracker);
        var healthyContext = healthyCollector.Capture(healthyUi);
        var healthyInput = OperationInputBinding.Capture(Guid.NewGuid().ToString("D"), input.SourceSha256,
            new ContextPrecondition { DocumentKey=healthyContext.DocumentKey, Revision=healthyContext.Revision }, target);
        var healthyJournal = new OperationJournal(Path.Combine(args[0], "durable-failure.jsonl"), target);
        var durableFailure = new ExecutionEngine(healthyCollector, healthyJournal).Execute(healthyUi,
            new ExecutionWorkItem(healthyInput, new byte[] { 1 }, admission));
        Require(durableFailure.State==ReceiptStates.FailedAfterStartUnknown && durableFailure.Started
            && !durableFailure.MayRetry && healthyJournal.IsHealthy
            && healthyJournal.Get(healthyInput.OperationId)?.Receipt?.State==ReceiptStates.FailedAfterStartUnknown,
            "successfully persisted genuine after-start failure was incorrectly relabelled");
        Console.WriteLine(JsonSerializer.Serialize(new {
            durable_failure_state=durableFailure.State, durable_failure_has_record=true,
            scope="actual linked Engine/Journal/Scheduler/Service; API stubs; no generated-source/native Revit invocation",
            first_receipt=first, empty_before_cancel=emptyBeforeCancel, journal_healthy=journal.IsHealthy,
            cancellation, stored_phase=stored!.Phase, mutation_count=doc.Native.Mutations,
            original_source_sha256=input.SourceSha256
        }));
        // This is the regression assertion. Old fallback is terminal-looking.
        return first.State==ReceiptStates.RunningUnknown ? 0 : 1;
    }
}
