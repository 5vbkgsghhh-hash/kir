using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Connector;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

internal static class CancellationTests
{
    public static readonly (string Name, Action Run)[] Cases =
    {
        ("cancel before enqueue prevents later generated invocation", BeforeEnqueue),
        ("cancel queued operation prevents actual queue drain from invoking", Queued),
        ("journal cancellation does not need compiler context or scheduler", NoModelCollaborators),
        ("cancel winner excludes concurrent durable start", CancelWins),
        ("start winner cannot be converted to cancellation", StartWins),
        ("every cancellation binding conflict preserves original journal bytes", BindingConflicts),
        ("cancel route authenticates target session and token before writing", Routes),
        ("cancel wire requires exact source-free complete binding", Wire),
        ("existing committed and started operations retain their original outcome", Existing),
        ("closed or expired admission cannot append a new cancellation", Closed),
        ("session close waits for an admitted durable cancellation", CloseRace),
        ("request mutation cannot change a captured cancellation binding", ImmutableInput),
        ("disposed owner cannot confirm cancellation or write through its lease", DisposedOwner),
        ("partial cancellation append fails closed without false terminal", PartialAppend),
        ("complete append followed by acknowledgement loss is recoverable by lookup", LostAcknowledgement),
        ("new session cancellation blocks old session queued execution", SessionRotation),
        ("cancel DTO sync and async framing preserve required nulls", DtoRoundTrip),
        ("cancel DTO forbidden values fail before any frame bytes", DtoForbidden),
        ("legacy request DTO framing bytes remain unchanged", LegacyDtoBytes),
    };
    private const string Source = "using Autodesk.Revit.DB; using Autodesk.Revit.UI; namespace Kir.Generated { public static class UserCode { public static object Execute(Document d, UIDocument u) { d.TestMutation(); return 1; } } }";
    private static readonly Lazy<byte[]> AssemblyBytes = new Lazy<byte[]>(Compile);
    private static void Check(bool condition, string message = "assertion failed") { if (!condition) throw new Exception(message); }
    private static string Serialize(object value) => JsonSerializer.Serialize(value);
    private static string Hash() => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Source))).ToLowerInvariant();
    private static string NewDirectory()
    {
        var root = Environment.GetEnvironmentVariable("KIR_TEST_ARTIFACT_ROOT");
        if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root))
            throw new InvalidOperationException("explicit existing KIR_TEST_ARTIFACT_ROOT is required");
        var path = Path.Combine(root, "cancel-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path; // Retain artifacts; this runner performs no directory cleanup.
    }
    private static byte[] Compile()
    {
        var references = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
            .Select(path => MetadataReference.CreateFromFile(path)).ToList();
        references.Add(MetadataReference.CreateFromFile(typeof(Document).Assembly.Location));
        var compilation = CSharpCompilation.Create("CancellationGeneratedFixture", new[] { CSharpSyntaxTree.ParseText(Source) },
            references, new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
        using var stream = new MemoryStream();
        var result = compilation.Emit(stream);
        Check(result.Success, string.Join("\n", result.Diagnostics));
        return stream.ToArray();
    }

    private sealed class Fixture : IDisposable
    {
        public readonly string Root = NewDirectory();
        public string PathName => Path.Combine(Root, "operations.jsonl");
        public readonly ConnectorTarget Target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2026");
        public readonly SessionAdmission Admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddHours(1));
        public readonly UIApplication Ui = new UIApplication();
        public readonly Document Document = new Document(new NativeDocument());
        public readonly DocumentRevisionTracker Tracker;
        public readonly ContextSnapshotCollector Collector;
        public readonly ContextQueryScheduler Context;
        public readonly OperationJournal Journal;
        public readonly ExecutionEngine Engine;
        public readonly ExternalEventScheduler Queue;
        public readonly ConnectorService Service;
        public Fixture(Action<string, byte[]>? append = null)
        {
            Ui.ActiveUIDocument = new UIDocument(Document);
            Tracker = new DocumentRevisionTracker(Ui.Application);
            Collector = new ContextSnapshotCollector(Tracker);
            Context = new ContextQueryScheduler(Collector);
            Journal = append == null ? new OperationJournal(PathName, Target) : new OperationJournal(PathName, append, Target);
            Engine = new ExecutionEngine(Collector, Journal);
            Queue = new ExternalEventScheduler(Engine);
            Service = NewService(Journal, Admission);
        }
        public ConnectorService NewService(OperationJournal journal, SessionAdmission admission) =>
            new ConnectorService("token", admission, Context, Queue, new CompilerHostClient(Root), journal, Target, Root);
        public OperationInputBinding Input()
        {
            var context = Collector.Capture(Ui);
            return OperationInputBinding.Capture(Guid.NewGuid().ToString("D"), Hash(),
                new ContextPrecondition { DocumentKey = context.DocumentKey, Revision = context.Revision,
                    ActiveViewId = context.ActiveViewId, SelectionDigest = context.SelectionDigest }, Target);
        }
        public ExecutionWorkItem Work(OperationInputBinding input) => new ExecutionWorkItem(input, AssemblyBytes.Value, Admission);
        public ConnectorRequest Request(OperationInputBinding input) => new ConnectorRequest
        {
            Protocol = ProtocolConstants.Version, RequestId = Guid.NewGuid().ToString("D"), Kind = RequestKinds.CancelBeforeStart,
            Target = input.Target, SessionId = Admission.SessionId, Token = "token", TimeoutMs = 1000,
            OperationId = input.OperationId, SourceSha256 = input.SourceSha256, Precondition = input.ToPrecondition(),
        };
        public ConnectorResponse Call(OperationInputBinding input) => Service.Handle(Request(input)).GetAwaiter().GetResult();
        public string Bytes() => File.Exists(PathName) ? File.ReadAllText(PathName) : "";
        public void Dispose() { Queue.Dispose(); Context.Dispose(); Tracker.Dispose(); ExternalEvent.NextRaise = null; }
    }
    private static void Cancelled(ConnectorResponse response)
    {
        Check(response.Ok && response.Status == "receipt" && response.Context == null);
        var receipt = response.Receipt!;
        Check(receipt.State == ReceiptStates.CancelledBeforeStart && !receipt.Started && receipt.MayRetry);
        Check(receipt.Changes == null && receipt.ResultJson == null && receipt.ResultError == null && !receipt.ResultTruncated);
        Check(receipt.TransactionEvidence == "not_observed" && receipt.SemanticEvidence == "unverified");
    }
    private static void BeforeEnqueue()
    {
        using var f = new Fixture(); var input = f.Input(); var cancelled = f.Call(input); Cancelled(cancelled);
        var bytes = f.Bytes(); var task = f.Queue.Enqueue(f.Work(input)); ExternalEvent.PumpAll(f.Ui);
        Check(Serialize(task.Result) == Serialize(cancelled.Receipt!) && f.Document.Native.Mutations == 0);
        Check(f.Bytes() == bytes && f.Journal.Get(input.OperationId)!.Phase == "terminal");
    }
    private static void Queued()
    {
        using var f = new Fixture(); var input = f.Input(); var task = f.Queue.Enqueue(f.Work(input));
        Check(!task.IsCompleted && f.Bytes() == ""); var response = f.Call(input); Cancelled(response);
        ExternalEvent.PumpAll(f.Ui); Check(task.Result.State == ReceiptStates.CancelledBeforeStart && f.Document.Native.Mutations == 0);
    }
    private static void NoModelCollaborators()
    {
        using var f = new Fixture(); var input = f.Input(); f.Ui.ActiveUIDocument = null!;
        f.Queue.Dispose(); f.Context.Dispose(); f.Tracker.Dispose();
        // Null collaborators make any unexpected context/compile/queue call red.
        var service = new ConnectorService("token", f.Admission, null!, null!, null!, f.Journal, f.Target, f.Root);
        Cancelled(service.Handle(f.Request(input)).GetAwaiter().GetResult());
        Check(f.Document.Native.Mutations == 0);
    }
    private static Action<string, byte[]> BlockFirst(ManualResetEventSlim entered, ManualResetEventSlim release)
    {
        var count = 0;
        return (path, bytes) =>
        {
            if (Interlocked.Increment(ref count) == 1) { entered.Set(); Check(release.Wait(5000), "append release deadline"); }
            OperationJournal.AppendDurably(path, bytes);
        };
    }
    private static void CancelWins()
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var f = new Fixture(BlockFirst(entered, release)); var input = f.Input();
        var cancel = Task.Run(() => f.Call(input)); Check(entered.Wait(5000));
        var start = Task.Run(() => f.Journal.TryStart(input, out _));
        release.Set(); Check(Task.WaitAll(new Task[] { cancel, start }, 5000));
        Cancelled(cancel.Result); Check(!start.Result && f.Journal.Get(input.OperationId)!.Phase == "terminal");
    }
    private static void StartWins()
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var f = new Fixture(BlockFirst(entered, release)); var input = f.Input();
        var start = Task.Run(() => f.Journal.TryStart(input, out _)); Check(entered.Wait(5000));
        var cancel = Task.Run(() => f.Call(input)); release.Set(); Check(Task.WaitAll(new Task[] { start, cancel }, 5000));
        Check(start.Result && !cancel.Result.Ok && cancel.Result.Status == ReceiptStates.RunningUnknown);
        Check(f.Journal.Get(input.OperationId)!.Phase == "started" && File.ReadAllLines(f.PathName).Length == 1);
    }
    private static void BindingConflicts()
    {
        using var f = new Fixture(); var input = f.Input(); Cancelled(f.Call(input)); var bytes = f.Bytes();
        foreach (var axis in new[] { "source", "document", "revision", "view", "selection", "null_view", "null_selection" })
        {
            var request = f.Request(input);
            if (axis == "source") request.SourceSha256 = new string('f', 64);
            if (axis == "document") request.Precondition!.DocumentKey += "other";
            if (axis == "revision") request.Precondition!.Revision++;
            if (axis == "view") request.Precondition!.ActiveViewId++;
            if (axis == "selection") request.Precondition!.SelectionDigest = "different";
            if (axis == "null_view") request.Precondition!.ActiveViewId = null;
            if (axis == "null_selection") request.Precondition!.SelectionDigest = null;
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "operation_conflict", axis);
            Check(f.Bytes() == bytes);
        }
        var exact = f.Request(input); exact.OperationId = Guid.Parse(input.OperationId).ToString("B").ToUpperInvariant();
        exact.SourceSha256 = input.SourceSha256.ToUpperInvariant(); Cancelled(f.Service.Handle(exact).GetAwaiter().GetResult());
        Check(f.Bytes() == bytes);
    }
    private static void Routes()
    {
        using var f = new Fixture(); var input = f.Input();
        foreach (var axis in new[] { "token", "session", "journal", "instance", "year", "recovery", "source" })
        {
            var request = f.Request(input);
            if (axis == "token") request.Token = "other";
            if (axis == "session") request.SessionId = Guid.NewGuid().ToString("D");
            if (axis == "journal") request.Target = new ConnectorTarget(Guid.NewGuid().ToString("D"), f.Target.InstanceId, "2026");
            if (axis == "instance") request.Target = new ConnectorTarget(f.Target.JournalId, Guid.NewGuid().ToString("D"), "2026");
            if (axis == "year") request.Target = new ConnectorTarget(f.Target.JournalId, f.Target.InstanceId, "2023");
            if (axis == "recovery") request.RecoveryTarget = f.Target;
            if (axis == "source") request.Source = "MUST-NOT-COMPILE-OR-ECHO";
            var response = f.Service.Handle(request).GetAwaiter().GetResult();
            Check(!response.Ok && response.Receipt == null && f.Bytes() == "", axis);
            Check(!Serialize(response).Contains("MUST-NOT-COMPILE-OR-ECHO"));
        }
    }
    private static Dictionary<string, object?> Payload(Fixture f, OperationInputBinding input) => new Dictionary<string, object?>
    {
        ["protocol"] = ProtocolConstants.Version, ["request_id"] = Guid.NewGuid().ToString("D"), ["kind"] = RequestKinds.CancelBeforeStart,
        ["target"] = f.Target, ["session_id"] = f.Admission.SessionId, ["token"] = "token", ["timeout_ms"] = 1000,
        ["operation_id"] = input.OperationId, ["source_sha256"] = input.SourceSha256,
        ["precondition"] = new Dictionary<string, object?> { ["document_key"] = input.DocumentKey, ["revision"] = input.Revision,
            ["active_view_id"] = input.ActiveViewId, ["selection_digest"] = input.SelectionDigest },
    };
    private static ConnectorRequest Framed(Dictionary<string, object?> payload)
    {
        using var stream = new MemoryStream(); JsonFraming.Write(stream, payload); stream.Position = 0;
        return JsonFraming.Read<ConnectorRequest>(stream);
    }
    private static void Wire()
    {
        using var f = new Fixture(); var input = f.Input();
        foreach (var field in Payload(f, input).Keys.Concat(new[] { "source", "recovery_target", "unknown", "revision", "active_view_id", "selection_digest", "negative_revision", "null_revision", "invalid_hash" }))
        {
            var payload = Payload(f, input);
            if (field == "source" || field == "recovery_target" || field == "unknown") payload[field] = null;
            else if (field == "revision" || field == "active_view_id" || field == "selection_digest") ((Dictionary<string, object?>)payload["precondition"]!).Remove(field);
            else if (field == "negative_revision") ((Dictionary<string, object?>)payload["precondition"]!)["revision"] = -1;
            else if (field == "null_revision") ((Dictionary<string, object?>)payload["precondition"]!)["revision"] = null;
            else if (field == "invalid_hash") payload["source_sha256"] = "wrong";
            else payload.Remove(field);
            var refused = false;
            try { refused = !f.Service.Handle(Framed(payload)).GetAwaiter().GetResult().Ok; }
            catch (Exception error) when (error is InvalidDataException || error is JsonException || error is ArgumentException) { refused = true; }
            Check(refused && f.Bytes() == "", field);
        }
        Cancelled(f.Service.Handle(Framed(Payload(f, input))).GetAwaiter().GetResult());
    }
    private static void Existing()
    {
        using var f = new Fixture(); var input = f.Input(); var work = f.Queue.Enqueue(f.Work(input)); ExternalEvent.PumpAll(f.Ui);
        var receipt = work.Result; Check(f.Document.Native.Mutations == 1); var bytes = f.Bytes();
        var response = f.Call(input); Check(response.Ok && Serialize(response.Receipt!) == Serialize(receipt) && f.Bytes() == bytes);
        var next = f.Input(); Check(f.Journal.TryStart(next, out _)); bytes = f.Bytes();
        response = f.Call(next); Check(!response.Ok && response.Status == ReceiptStates.RunningUnknown && response.Receipt!.Started);
        Check(f.Bytes() == bytes);
    }
    private static void Closed()
    {
        using var f = new Fixture(); var input = f.Input(); var first = f.Call(input); Cancelled(first); f.Admission.Close();
        Check(Serialize(f.Call(input).Receipt!) == Serialize(first.Receipt!));
        var other = f.Input(); var bytes = f.Bytes(); Check(f.Call(other).Status == "disabled" && f.Bytes() == bytes);
        var now = DateTime.UtcNow; var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), now.AddMinutes(1), () => now);
        var service = f.NewService(f.Journal, admission); now = now.AddMinutes(2);
        var request = f.Request(other); request.SessionId = admission.SessionId;
        Check(service.Handle(request).GetAwaiter().GetResult().Status == "disabled" && f.Bytes() == bytes);
    }
    private static void CloseRace()
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var f = new Fixture(BlockFirst(entered, release)); var input = f.Input();
        var cancel = Task.Run(() => f.Call(input)); Check(entered.Wait(5000));
        var close = Task.Run(() => f.Admission.Close());
        Check(!close.Wait(30), "Close passed an admitted durable append"); release.Set();
        Check(Task.WaitAll(new Task[] { cancel, close }, 5000)); Cancelled(cancel.Result); Check(!f.Admission.IsOpen);
    }
    private static void ImmutableInput()
    {
        using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var f = new Fixture(BlockFirst(entered, release)); var input = f.Input(); var request = f.Request(input);
        var cancel = Task.Run(() => f.Service.Handle(request).GetAwaiter().GetResult()); Check(entered.Wait(5000));
        request.Precondition!.DocumentKey = "mutated-after-capture"; request.Precondition.Revision = 999;
        request.OperationId = Guid.NewGuid().ToString("D"); request.SourceSha256 = new string('f', 64);
        release.Set(); Check(cancel.Wait(5000)); Cancelled(cancel.Result);
        Check(f.Journal.Get(input.OperationId)!.Input!.Matches(input));
    }
    private static void DisposedOwner()
    {
        var root = NewDirectory();
        using var owner = JournalOwner.CreateNew(root,
            new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2026"));
        var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddHours(1));
        var service = new ConnectorService("token", admission, null!, null!, null!, owner.Journal, owner.Target, root);
        var input = new OperationInputBinding(Guid.NewGuid().ToString("D"), Hash(), "opaque-document", 0, null, null, owner.Target);
        owner.Dispose();
        var response = service.Handle(new ConnectorRequest { Protocol = ProtocolConstants.Version, Kind = RequestKinds.CancelBeforeStart,
            RequestId = "cancel", Target = owner.Target, SessionId = admission.SessionId, Token = "token", TimeoutMs = 1000,
            OperationId = input.OperationId, SourceSha256 = input.SourceSha256, Precondition = input.ToPrecondition() }).GetAwaiter().GetResult();
        Check(!response.Ok && response.Status == "journal_unavailable" && response.Receipt == null && !owner.Journal.IsHealthy);
    }
    private static void PartialAppend()
    {
        using var f = new Fixture((path, bytes) => { File.WriteAllBytes(path, bytes.Take(bytes.Length / 2).ToArray()); throw new IOException("private diagnostic"); });
        var input = f.Input(); var response = f.Call(input);
        Check(!response.Ok && response.Status == "journal_unavailable" && response.Receipt == null && !f.Journal.IsHealthy);
        Check(!Serialize(response).Contains("private diagnostic")); var bytes = f.Bytes();
        Check(!new OperationJournal(f.PathName, f.Target).IsHealthy && f.Bytes() == bytes);
    }
    private static void LostAcknowledgement()
    {
        using var f = new Fixture((path, bytes) => { OperationJournal.AppendDurably(path, bytes); throw new IOException("post-append acknowledgement lost"); });
        var input = f.Input(); var response = f.Call(input);
        Check(!response.Ok && response.Status == "journal_unavailable" && response.Receipt == null);
        var bytes = f.Bytes(); var recovered = new OperationJournal(f.PathName, f.Target); Check(recovered.IsHealthy);
        var service = f.NewService(recovered, f.Admission); response = service.Handle(f.Request(input)).GetAwaiter().GetResult();
        Cancelled(response); Check(f.Bytes() == bytes);
    }
    private static void SessionRotation()
    {
        using var f = new Fixture(); var input = f.Input(); var queued = f.Queue.Enqueue(f.Work(input)); f.Admission.Close();
        var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddHours(1));
        var service = f.NewService(f.Journal, admission); var request = f.Request(input); request.SessionId = admission.SessionId;
        Cancelled(service.Handle(request).GetAwaiter().GetResult()); ExternalEvent.PumpAll(f.Ui);
        Check(queued.Result.State == ReceiptStates.CancelledBeforeStart && f.Document.Native.Mutations == 0);
    }

    private static void DtoRoundTrip()
    {
        using var f = new Fixture(); var request = f.Request(f.Input());
        request.Precondition!.ActiveViewId = null; request.Precondition.SelectionDigest = null;
        // Counterfactual old producer: generic DTO serialization includes the
        // forbidden top-level nulls and really is rejected by the same reader.
        using (var oldFrame = new MemoryStream())
        {
            JsonFraming.WriteRawAsync(oldFrame, JsonSerializer.SerializeToUtf8Bytes(request, JsonFraming.Options), CancellationToken.None).GetAwaiter().GetResult();
            oldFrame.Position = 0; var rejected = false;
            try { JsonFraming.Read<ConnectorRequest>(oldFrame); }
            catch (InvalidDataException) { rejected = true; }
            Check(rejected, "old DTO encoding unexpectedly passed the strict cancel reader");
        }
        foreach (var asyncWriter in new[] { false, true })
        {
            using var stream = new MemoryStream();
            if (asyncWriter) JsonFraming.WriteAsync(stream, request, CancellationToken.None).GetAwaiter().GetResult();
            else JsonFraming.Write(stream, request);
            using var parsed = JsonDocument.Parse(stream.ToArray().Skip(4).ToArray());
            var root = parsed.RootElement;
            Check(root.EnumerateObject().Count() == 10 && !root.TryGetProperty("source", out _) && !root.TryGetProperty("recovery_target", out _));
            var condition = root.GetProperty("precondition");
            Check(condition.EnumerateObject().Count() == 4
                && condition.GetProperty("active_view_id").ValueKind == JsonValueKind.Null
                && condition.GetProperty("selection_digest").ValueKind == JsonValueKind.Null);
            stream.Position = 0;
            var decoded = JsonFraming.Read<ConnectorRequest>(stream);
            Check(decoded.Precondition!.ActiveViewId == null && decoded.Precondition.SelectionDigest == null);
            Cancelled(f.Service.Handle(decoded).GetAwaiter().GetResult());
        }
    }

    private static void DtoForbidden()
    {
        using var f = new Fixture();
        foreach (var fault in new[] { "source", "recovery", "precondition" })
        foreach (var asyncWriter in new[] { false, true })
        {
            var request = f.Request(f.Input());
            if (fault == "source") request.Source = "must not disappear";
            if (fault == "recovery") request.RecoveryTarget = f.Target;
            if (fault == "precondition") request.Precondition = null;
            using var stream = new MemoryStream(); var refused = false;
            try
            {
                if (asyncWriter) JsonFraming.WriteAsync(stream, request, CancellationToken.None).GetAwaiter().GetResult();
                else JsonFraming.Write(stream, request);
            }
            catch (InvalidDataException) { refused = true; }
            Check(refused && stream.Length == 0, fault);
        }
    }

    private static void LegacyDtoBytes()
    {
        using var f = new Fixture();
        foreach (var kind in new[] { RequestKinds.Ping, RequestKinds.Context, RequestKinds.Execute, RequestKinds.Receipt, RequestKinds.RecoverReceipt })
        {
            var request = f.Request(f.Input()); request.Kind = kind;
            var expected = JsonSerializer.SerializeToUtf8Bytes(request, JsonFraming.Options);
            using var stream = new MemoryStream(); JsonFraming.Write(stream, request);
            Check(stream.ToArray().Skip(4).SequenceEqual(expected), kind);
        }
    }
}
