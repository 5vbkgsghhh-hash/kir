using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Connector;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;

internal static class ExecutionBindingTests
{
    public static readonly (string Name, Action Run)[] Cases =
    {
        ("v4 execution requires a non-negative document revision", RequiredRevision),
        ("wire rejects v2 and unknown precondition fields", WireVersion),
        ("actual framed requests require every routing field", FramedRequiredFields),
        ("actual framed JSON refuses duplicate and escaped-equivalent keys", FramedDuplicateKeys),
        ("actual framed JSON refuses malformed UTF8 without substitution", FramedUtf8),
        ("each target mismatch is refused before compilation or effect", TargetMismatch),
        ("missing and stale session routes cannot execute", SessionRoute),
        ("native document version must match the declared execution target", NativeTargetVersion),
        ("historical recovery uses original target but current response route", HistoricalRecovery),
        ("unavailable foreign recovery cannot turn into not-found", RecoveryFailures),
        ("full binding distinguishes every input and preserves null semantics", BindingAxes),
        ("source hash and UUID case normalize to the same binding", CanonicalIdentity),
        ("queued assembly and context detach from mutable caller data", DetachedQueue),
        ("real execution queue invokes tiny generated assembly once", QueueExecution),
        ("queued conflicting requests cannot overwrite first receipt", QueuedConflict),
        ("every binding conflict preserves exact durable bytes", DurableConflicts),
        ("exact retry ignores active document switch and missing document", ExactRetry),
        ("restarted journal returns original receipt without execution", RestartRetry),
        ("started-only lookup is running unknown after restart", StartedLookup),
        ("queued but unstarted lookup does not grant replay permission", QueuedLookup),
        ("denied external event cannot execute when later queue drains", DeniedThenDrain),
        ("denied duplicate of a started request cannot grant retry", DeniedAfterStart),
        ("denied duplicate with unavailable journal retains uncertainty", DeniedUnhealthy),
        ("changed native context refuses invocation before durable start", StaleContext),
        ("mutable returned receipt and manifest cannot alter index", DetachedJournal),
        ("first terminal receipt remains authoritative", FirstTerminal),
        ("legacy v0 and v3 remain read-only archives without a v4 target", LegacyArchive),
        ("invalid lookup differs from unavailable journal", LookupFailures),
        ("partial start append poisons journal before invocation", PartialStart),
        ("complete start write then failure cannot invoke or retry", CompleteStartFailure),
        ("partial terminal append preserves uncertainty and poisons journal", PartialTerminal),
        ("complete terminal write then failure recovers original durable receipt", CompleteTerminalFailure),
        ("complete JSON without record delimiter is not healthy recovery", UnterminatedRecord),
        ("corrupt bindings transitions and duplicate JSON keys fail closed", CorruptJournal),
        ("invalid UTF8 cannot silently change a recovered journal binding", InvalidJournalUtf8),
        ("journal BOM encodings cannot be auto-converted before UTF8 append", JournalBom),
        ("valid Unicode journal identities survive strict recovery exactly", UnicodeJournal),
        ("native context command captures through actual scheduler", ContextRoute),
        ("a change in an unbound document is a loud terminal refusal", ForeignDocumentChange),
        ("changes in the bound document keep the ordinary completed receipt", BoundDocumentChanges),
    };

    private const string Source = "using Autodesk.Revit.DB; using Autodesk.Revit.UI; namespace Kir.Generated { public static class UserCode { public static object Execute(Document document, UIDocument ui) { document.TestMutation(); return new { value = 42 }; } } }";
    private static readonly Lazy<byte[]> Generated = new Lazy<byte[]>(CompileAssembly);
    private static string Hash(string source) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(source))).ToLowerInvariant();
    private static void Check(bool value, string message = "assertion failed") { if (!value) throw new Exception(message); }
    private static T Throws<T>(Action action) where T : Exception
    {
        try { action(); } catch (T error) { return error; }
        throw new Exception("expected " + typeof(T).Name);
    }
    private static byte[] CompileAssembly()
    {
        var references = ((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")!).Split(Path.PathSeparator)
            .Select(path => MetadataReference.CreateFromFile(path)).ToList();
        references.Add(MetadataReference.CreateFromFile(typeof(Document).Assembly.Location));
        var compilation = CSharpCompilation.Create("KirGeneratedBindingFixture", new[] { CSharpSyntaxTree.ParseText(Source) },
            references, new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary));
        using var stream = new MemoryStream(); var result = compilation.Emit(stream);
        Check(result.Success, string.Join("\n", result.Diagnostics));
        return stream.ToArray();
    }

    internal sealed class Fixture : IDisposable
    {
        public readonly string DirectoryPath = Path.Combine(Path.GetTempPath(), "kir-context-binding-" + Guid.NewGuid().ToString("N"));
        public string JournalPath => Path.Combine(DirectoryPath, "operations.jsonl");
        public readonly UIApplication Ui = new UIApplication();
        public readonly Document Document = new Document(new NativeDocument());
        public readonly DocumentRevisionTracker Tracker;
        public readonly ContextSnapshotCollector Collector;
        public readonly ContextQueryScheduler Context;
        public readonly OperationJournal Journal;
        public readonly ExecutionEngine Engine;
        public readonly ExternalEventScheduler Queue;
        public readonly ConnectorService Service;
        public readonly ConnectorTarget Target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2026");
        public readonly string SessionId = Guid.NewGuid().ToString("D");
        public readonly SessionAdmission Admission;
        public Fixture(Action<string, byte[]>? append = null, string? targetYear = null)
        {
            if (targetYear != null) Target = new ConnectorTarget(Target.JournalId, Target.InstanceId, targetYear);
            Admission = new SessionAdmission(SessionId, DateTime.UtcNow.AddHours(1));
            Directory.CreateDirectory(DirectoryPath);
            Ui.ActiveUIDocument = new UIDocument(Document);
            Tracker = new DocumentRevisionTracker(Ui.Application);
            Collector = new ContextSnapshotCollector(Tracker);
            Context = new ContextQueryScheduler(Collector);
            Journal = append == null ? new OperationJournal(JournalPath, Target) : new OperationJournal(JournalPath, append, Target);
            Engine = new ExecutionEngine(Collector, Journal);
            Queue = new ExternalEventScheduler(Engine);
            Service = CreateService(Journal);
        }
        public ConnectorService CreateService(OperationJournal journal) => new ConnectorService("token", Admission,
            Context, Queue, new CompilerHostClient(DirectoryPath), journal, Target, DirectoryPath);
        public OperationInputBinding Input(string? id = null)
        {
            var snapshot = Collector.Capture(Ui);
            return new OperationInputBinding(id ?? Guid.NewGuid().ToString("D"), Hash(Source), snapshot.DocumentKey,
                snapshot.Revision, snapshot.ActiveViewId, snapshot.SelectionDigest, Target);
        }
        public ExecutionWorkItem Work(OperationInputBinding input) => new ExecutionWorkItem(input, Generated.Value, Admission);
        public ConnectorRequest Request(OperationInputBinding input, string kind = RequestKinds.Execute) => new ConnectorRequest
        {
            Protocol = ProtocolConstants.Version, Token = "token", RequestId = "request", Kind = kind,
            Target = Target, SessionId = SessionId,
            OperationId = input.OperationId, Source = Source, SourceSha256 = input.SourceSha256,
            Precondition = input.ToPrecondition(), TimeoutMs = 1000,
        };
        public OperationReceipt Run(OperationInputBinding input)
        {
            var task = Queue.Enqueue(Work(input)); ExternalEvent.PumpAll(Ui); return task.GetAwaiter().GetResult();
        }
        public string Bytes() => File.ReadAllText(JournalPath);
        public void Dispose()
        {
            Queue.Dispose(); Context.Dispose(); Tracker.Dispose(); ExternalEvent.NextRaise = null;
            Directory.Delete(DirectoryPath, true);
        }
    }

    private static OperationInputBinding Change(OperationInputBinding input, string? source = null, string? document = null,
        long? revision = null, long? view = null, string? selection = null, bool nullView = false, bool nullSelection = false) =>
        new OperationInputBinding(input.OperationId, source ?? input.SourceSha256, document ?? input.DocumentKey,
            revision ?? input.Revision, nullView ? null : view ?? input.ActiveViewId,
            nullSelection ? null : selection ?? input.SelectionDigest, input.Target);
    private static IEnumerable<OperationInputBinding> Variants(OperationInputBinding input)
    {
        yield return Change(input, source: Hash(Source + " "));
        yield return Change(input, document: input.DocumentKey + "different");
        yield return Change(input, revision: input.Revision + 1);
        yield return Change(input, view: input.ActiveViewId + 1);
        yield return Change(input, selection: "different");
        yield return Change(input, nullView: true);
        yield return Change(input, nullSelection: true);
    }
    private static OperationReceipt Terminal(OperationInputBinding input, string result = "42") => new OperationReceipt
    {
        Target = input.Target,
        OperationId = input.OperationId, SourceSha256 = input.SourceSha256, DocumentKey = input.DocumentKey,
        Precondition = input.ToPrecondition(), State = ReceiptStates.InvocationCompleted, Started = true, MayRetry = false,
        ResultJson = result, Changes = new ChangeManifest { Added = { 7 } }, TimestampUtc = DateTime.UtcNow.ToString("O"),
    };
    private static void RequiredRevision()
    {
        using var f = new Fixture(); var input = f.Input();
        foreach (var revision in new long?[] { null, -1 })
        {
            var request = f.Request(input); request.Precondition!.Revision = revision;
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "invalid_request");
        }
        var missing = f.Request(input); missing.Precondition = null;
        Check(f.Service.Handle(missing).GetAwaiter().GetResult().Status == "invalid_request");
        var allowed = f.Service.Handle(f.Request(input)).GetAwaiter().GetResult();
        Check(allowed.Status == "compile_rejected", "valid revision must reach compiler, not be refused as malformed");
        Check(!File.Exists(f.JournalPath));
    }
    private static void WireVersion()
    {
        using var f = new Fixture(); var request = f.Request(f.Input()); request.Protocol = "kir-revit-connector/2";
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "protocol_mismatch");
        Throws<JsonException>(() => JsonSerializer.Deserialize<ContextPrecondition>("{\"document_key\":\"x\",\"revision\":0,\"revison\":0}"));
        Throws<JsonException>(() => JsonSerializer.Deserialize<ConnectorRequest>("{\"unknown\":true}"));
        var noProtocol = JsonSerializer.Deserialize<ConnectorRequest>("{}")!;
        Check(f.Service.Handle(noProtocol).GetAwaiter().GetResult().Status == "protocol_mismatch");
        Check(ProtocolConstants.Version == "kir-revit-connector/4");
    }
    private static void BindingAxes()
    {
        using var f = new Fixture(); var input = f.Input();
        foreach (var variant in Variants(input)) Check(!input.Matches(variant));
        var empty = Change(input, selection: ""); Check(!empty.Matches(Change(input, nullSelection: true)));
        Check(!Change(input, view: 0).Matches(Change(input, nullView: true)));
        Throws<ArgumentException>(() => new OperationInputBinding(input.OperationId, "bad", input.DocumentKey, 0, null, null, input.Target));
    }

    private static ConnectorRequest ReadFrame(byte[] payload)
    {
        using var stream = new MemoryStream();
        using (var writer = new BinaryWriter(stream, Encoding.UTF8, true))
        { writer.Write(payload.Length); writer.Write(payload); }
        stream.Position = 0;
        return JsonFraming.Read<ConnectorRequest>(stream);
    }

    private static void FramedRequiredFields()
    {
        using var f = new Fixture();
        var valid = JsonSerializer.Serialize(f.Request(f.Input(), RequestKinds.Ping));
        Check(f.Service.Handle(ReadFrame(Encoding.UTF8.GetBytes(valid))).GetAwaiter().GetResult().Status == "ready");
        foreach (var field in new[] { "protocol", "request_id", "token", "kind", "target", "session_id" })
        {
            var json = JsonNode.Parse(valid)!.AsObject(); json.Remove(field);
            var request = ReadFrame(Encoding.UTF8.GetBytes(json.ToJsonString()));
            var response = f.Service.Handle(request).GetAwaiter().GetResult();
            Check(!response.Ok && response.Status != "ready", "framing silently supplied missing " + field);
            if (field == "protocol") Check(response.Status == "protocol_mismatch");
        }
        Check(!File.Exists(f.JournalPath) && f.Document.Native.Mutations == 0);
    }

    private static void FramedDuplicateKeys()
    {
        using var f = new Fixture();
        var valid = JsonSerializer.Serialize(f.Request(f.Input(), RequestKinds.Ping));
        foreach (var malformed in new[] {
            valid.Insert(1, "\"kind\":\"context\","),
            valid.Replace("\"revision\":0", "\"revision\":999,\"revision\":0"),
            valid.Replace("\"instance_id\":", "\"instance_id\":\"" + Guid.NewGuid().ToString("D") + "\",\"instance_id\":"),
            valid.Insert(1, "\"\\u006bind\":\"context\",") })
        {
            Check(malformed != valid);
            Throws<InvalidDataException>(() => ReadFrame(Encoding.UTF8.GetBytes(malformed)));
        }
        Check(!File.Exists(f.JournalPath));
    }

    private static void FramedUtf8()
    {
        using var f = new Fixture(); var request = f.Request(f.Input(), RequestKinds.Ping); request.RequestId = "request-X";
        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(request)).Select(b => b == (byte)'X' ? (byte)0xFF : b).ToArray();
        Check(bytes.Count(b => b == 0xFF) == 1);
        var refused = false;
        try { ReadFrame(bytes); }
        catch (Exception error) when (error is JsonException || error is DecoderFallbackException || error is InvalidDataException)
        { refused = true; }
        Check(refused && !File.Exists(f.JournalPath));
    }
    private static void TargetMismatch()
    {
        using var f = new Fixture(); var input = f.Input();
        foreach (var target in new[] {
            new ConnectorTarget(Guid.NewGuid().ToString("D"), f.Target.InstanceId, f.Target.RevitVersion),
            new ConnectorTarget(f.Target.JournalId, Guid.NewGuid().ToString("D"), f.Target.RevitVersion),
            new ConnectorTarget(f.Target.JournalId, f.Target.InstanceId, "2023") })
        {
            var request = f.Request(input); request.Target = target;
            var response = f.Service.Handle(request).GetAwaiter().GetResult();
            Check(response.Status == "target_mismatch", "actual status=" + response.Status);
            Check(response.Target!.Matches(f.Target) && response.SessionId == f.SessionId);
            Check(!File.Exists(f.JournalPath) && f.Document.Native.Mutations == 0);
            var foreign = new OperationInputBinding(input.OperationId, input.SourceSha256, input.DocumentKey,
                input.Revision, input.ActiveViewId, input.SelectionDigest, target);
            Check(!input.Matches(foreign));
            Check(f.Engine.Execute(f.Ui, f.Work(foreign)).State == "target_mismatch");
            Check(Throws<JournalBindingException>(() => f.Journal.TryStart(foreign, out _)).Status == "journal_target_mismatch");
            Check(!File.Exists(f.JournalPath));
        }
    }

    private static void SessionRoute()
    {
        using var f = new Fixture(); var input = f.Input();
        var missing = f.Request(input); missing.Target = null;
        Check(f.Service.Handle(missing).GetAwaiter().GetResult().Status == "invalid_request");
        foreach (var session in new[] { "", "bad", Guid.NewGuid().ToString("D") })
        {
            var request = f.Request(input); request.SessionId = session;
            var expected = Guid.TryParse(session, out _) ? "session_mismatch" : "invalid_request";
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == expected);
        }
        Check(!File.Exists(f.JournalPath) && f.Document.Native.Mutations == 0);
        var original = f.Run(input); var bytes = f.Bytes();
        var session2 = Guid.NewGuid().ToString("D");
        var rotated = new ConnectorService("newtoken", new SessionAdmission(session2, DateTime.UtcNow.AddHours(1)), f.Context, f.Queue,
            new CompilerHostClient(f.DirectoryPath), f.Journal, f.Target, f.DirectoryPath);
        var retry = f.Request(input); retry.Token = "newtoken"; retry.SessionId = session2;
        var response = rotated.Handle(retry).GetAwaiter().GetResult();
        Check(response.SessionId == session2 && JsonSerializer.Serialize(response.Receipt) == JsonSerializer.Serialize(original));
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 1);
    }

    private static void NativeTargetVersion()
    {
        using var f = new Fixture(targetYear: "2023"); // The production-linked stub exposes native2026.
        var response = f.Run(f.Input());
        Check(response.State == ReceiptStates.ContextChangedBeforeStart && !response.Started);
        Check(f.Document.Native.Mutations == 0);
        var capture = f.Service.Handle(f.Request(f.Input(), RequestKinds.Context));
        ExternalEvent.PumpAll(f.Ui);
        Check(capture.GetAwaiter().GetResult().Status == "context_target_mismatch");
    }

    private static void HistoricalRecovery()
    {
        foreach (var terminal in new[] { false, true })
        {
            using var f = new Fixture(); var originalTarget = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2023");
            var input = new OperationInputBinding(Guid.NewGuid().ToString("D"), Hash(Source), "old-doc-token", 8, null, null, originalTarget);
            OperationReceipt? original = null;
            using (var owner = JournalOwner.CreateNew(f.DirectoryPath, originalTarget))
            {
                Check(owner.Journal.TryStart(input, out _));
                if (terminal) original = owner.Journal.AppendTerminal(input, Terminal(input)).Receipt;
            }
            var path = Path.Combine(f.DirectoryPath, "journals", originalTarget.JournalId, "operations.jsonl");
            var bytes = File.ReadAllBytes(path);
            var request = f.Request(f.Input(), RequestKinds.RecoverReceipt);
            request.RecoveryTarget = originalTarget; request.OperationId = input.OperationId;
            var response = f.Service.Handle(request).GetAwaiter().GetResult();
            Check(response.Target!.Matches(f.Target) && response.SessionId == f.SessionId);
            Check(response.Receipt!.Target!.Matches(originalTarget) && !response.Receipt.MayRetry);
            Check(response.Status == (terminal ? "receipt" : ReceiptStates.RunningUnknown));
            if (terminal) Check(JsonSerializer.Serialize(response.Receipt) == JsonSerializer.Serialize(original));
            Check(File.ReadAllBytes(path).SequenceEqual(bytes) && f.Document.Native.Mutations == 0);
            request.OperationId = Guid.NewGuid().ToString("D");
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "not_found_unconfirmed");
        }
    }

    private static void RecoveryFailures()
    {
        using var f = new Fixture(); var target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2023");
        var request = f.Request(f.Input(), RequestKinds.RecoverReceipt);
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "invalid_request");
        request.RecoveryTarget = target;
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "journal_unavailable");
        using (JournalOwner.CreateNew(f.DirectoryPath, target))
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "journal_lease_unavailable");
        request.RecoveryTarget = new ConnectorTarget(target.JournalId, Guid.NewGuid().ToString("D"), target.RevitVersion);
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "journal_target_mismatch");
        request.OperationId = "bad";
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "invalid_request");
        Check(f.Document.Native.Mutations == 0 && !File.Exists(f.JournalPath));
    }
    private static void CanonicalIdentity()
    {
        using var f = new Fixture(); var input = f.Input();
        var alias = new OperationInputBinding(Guid.Parse(input.OperationId).ToString("B").ToUpperInvariant(), input.SourceSha256.ToUpperInvariant(),
            input.DocumentKey, input.Revision, input.ActiveViewId, input.SelectionDigest, input.Target);
        Check(input.Matches(alias)); f.Run(input); var bytes = f.Bytes();
        var request = f.Request(alias); request.OperationId = Guid.Parse(input.OperationId).ToString("N").ToUpperInvariant();
        request.SourceSha256 = input.SourceSha256.ToUpperInvariant();
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Receipt!.State == ReceiptStates.InvocationCompleted);
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 1);
    }
    private static void DetachedQueue()
    {
        using var f = new Fixture(); var original = f.Input(); var request = f.Request(original);
        var binding = OperationInputBinding.Capture(request.OperationId!, request.SourceSha256!, request.Precondition!, request.Target!);
        var bytes = (byte[])Generated.Value.Clone(); var work = new ExecutionWorkItem(binding, bytes, f.Admission);
        var pending = f.Queue.Enqueue(work);
        request.Source = "different source"; request.SourceSha256 = Hash(request.Source); request.Precondition!.DocumentKey = "different";
        request.Target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), "2023");
        request.Precondition.Revision = 999; request.Precondition.ActiveViewId = null; request.Precondition.SelectionDigest = null;
        Array.Clear(bytes); Array.Clear(work.AssemblyBytes); work.Precondition.Revision = -1;
        ExternalEvent.PumpAll(f.Ui);
        var receipt = pending.GetAwaiter().GetResult();
        Check(receipt.State == ReceiptStates.InvocationCompleted && receipt.SourceSha256 == Hash(Source));
        Check(original.Matches(OperationInputBinding.Capture(receipt.OperationId, receipt.SourceSha256, receipt.Precondition!, receipt.Target!)));
        Check(f.Document.Native.Mutations == 1);
    }
    private static void QueueExecution()
    {
        using var f = new Fixture(); var input = f.Input(); var receipt = f.Run(input);
        Check(receipt.State == ReceiptStates.InvocationCompleted && receipt.Started && !receipt.MayRetry);
        Check(receipt.ResultJson == "{\"value\":42}" && receipt.SemanticEvidence == "unverified");
        Check(f.Document.Native.Mutations == 1 && File.ReadAllLines(f.JournalPath).Length == 2);
        Check(f.Journal.Get(input.OperationId)!.Input!.Matches(input));
    }
    // A document nobody bound is changed WHILE the generated assembly runs. The
    // stub's MutationHook is the seam: the fixture's own generated source calls
    // TestMutation(), so the foreign event is raised inside Invoke, exactly
    // where the engine's handler is subscribed. Before the fix this event was
    // filtered out and the receipt said invocation_completed with a quiet
    // manifest — the mutation of a stranger's model left no evidence at all.
    private static void ForeignDocumentChange()
    {
        using var f = new Fixture(); var input = f.Input();
        var stranger = new Document(new NativeDocument());
        f.Document.MutationHook = () => f.Ui.Application.Changed(stranger, "stranger edit");
        var receipt = f.Run(input);
        Check(receipt.State == ReceiptStates.ForeignDocumentChanged, "foreign change must be terminal, not filtered");
        Check(receipt.Started && !receipt.MayRetry, "retry stays forbidden");
        Check(receipt.ResultJson == null && receipt.ResultError == null && !receipt.ResultTruncated,
            "a partial effect must not be published as a result");
        Check(receipt.Error != null && receipt.Error.Contains("other than the bound document"), "the refusal names itself");
        Check(receipt.Error!.Contains("stranger edit"), "the foreign transaction name reaches the receipt");
        Check(f.Document.Native.Mutations == 1, "the bound document was still touched once");
        Check(File.ReadAllLines(f.JournalPath).Length == 2, "the terminal receipt is durable");
        Check(f.Journal.GetReceipt(input.OperationId)!.State == ReceiptStates.ForeignDocumentChanged);
    }

    // The other half of the same seam: events of the BOUND document, including
    // several of them and a manifest that stays empty, must behave exactly as
    // before the fix.
    private static void BoundDocumentChanges()
    {
        using var f = new Fixture(); var input = f.Input();
        f.Document.MutationHook = () =>
        {
            f.Ui.Application.Changed(f.Document, "first");
            f.Ui.Application.Changed(f.Document, "second");
        };
        var receipt = f.Run(input);
        Check(receipt.State == ReceiptStates.InvocationCompleted && receipt.Started && !receipt.MayRetry);
        Check(receipt.ResultJson == "{\"value\":42}", "the ordinary result still reaches the receipt");
        Check(receipt.Changes != null && receipt.Changes.IsEmpty, "the stub raises no element ids");
        Check(receipt.TransactionEvidence == "changes_not_observed", "an empty manifest keeps its old evidence");
        Check(receipt.Changes!.TransactionNames.Count == 2, "both events of the bound document were captured");
        Check(receipt.Error == null);
    }

    private static void QueuedConflict()
    {
        using var f = new Fixture(); var input = f.Input(); var first = f.Queue.Enqueue(f.Work(input));
        var second = f.Queue.Enqueue(f.Work(Change(input, revision: input.Revision + 1)));
        // Both requests are queued before the first durable start exists.
        ExternalEvent.PumpAll(f.Ui);
        Check(first.Result.State == ReceiptStates.InvocationCompleted && second.Result.State == ReceiptStates.OperationConflict);
        Check(f.Document.Native.Mutations == 1 && File.ReadAllLines(f.JournalPath).Length == 2);
        Check(f.Journal.GetReceipt(input.OperationId)!.State == ReceiptStates.InvocationCompleted);
        var bytes = f.Bytes(); f.Engine.Execute(f.Ui, f.Work(Change(input, document: "other")));
        Check(bytes == f.Bytes());
    }
    private static void DurableConflicts()
    {
        using var f = new Fixture(); var input = f.Input(); f.Run(input); var bytes = f.Bytes();
        foreach (var variant in Variants(input))
        {
            var request = f.Request(variant);
            if (variant.SourceSha256 != input.SourceSha256) request.Source = Source + " ";
            Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == ReceiptStates.OperationConflict);
            Check(f.Engine.Execute(f.Ui, f.Work(variant)).State == ReceiptStates.OperationConflict);
            Check(f.Bytes() == bytes && f.Journal.Get(input.OperationId)!.Input!.Matches(input));
        }
        Check(f.Document.Native.Mutations == 1);
    }
    private static void ExactRetry()
    {
        using var f = new Fixture(); var input = f.Input(); var original = f.Run(input); var bytes = f.Bytes();
        foreach (var active in new UIDocument?[] { new UIDocument(new Document(new NativeDocument())), null })
        {
            f.Ui.ActiveUIDocument = active!;
            var receipt = f.Engine.Execute(f.Ui, f.Work(input));
            Check(JsonSerializer.Serialize(receipt) == JsonSerializer.Serialize(original));
            Check(f.Service.Handle(f.Request(input)).GetAwaiter().GetResult().Receipt!.TimestampUtc == original.TimestampUtc);
        }
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 1);
    }
    private static void RestartRetry()
    {
        using var f = new Fixture(); var input = f.Input(); var original = f.Run(input); var restarted = new OperationJournal(f.JournalPath, f.Target);
        f.Ui.ActiveUIDocument = null!;
        Check(restarted.IsHealthy);
        Check(new ExecutionEngine(f.Collector, restarted).Execute(f.Ui, f.Work(input)).TimestampUtc == original.TimestampUtc);
        Check(f.CreateService(restarted).Handle(f.Request(input)).GetAwaiter().GetResult().Receipt!.TimestampUtc == original.TimestampUtc);
        Check(f.Document.Native.Mutations == 1);
    }
    private static void StartedLookup()
    {
        using var f = new Fixture(); var input = f.Input(); Check(f.Journal.TryStart(input, out _)); var bytes = f.Bytes();
        var restarted = new OperationJournal(f.JournalPath, f.Target); var service = f.CreateService(restarted);
        var lookup = service.Handle(f.Request(input, RequestKinds.Receipt)).GetAwaiter().GetResult();
        Check(!lookup.Ok && lookup.Status == ReceiptStates.RunningUnknown && lookup.Receipt!.Started && !lookup.Receipt.MayRetry);
        Check(service.Handle(f.Request(input)).GetAwaiter().GetResult().Status == ReceiptStates.RunningUnknown);
        Check(new ExecutionEngine(f.Collector, restarted).Execute(f.Ui, f.Work(input)).State == ReceiptStates.RunningUnknown);
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 0);
    }
    private static void QueuedLookup()
    {
        using var f = new Fixture(); var input = f.Input(); var task = f.Queue.Enqueue(f.Work(input));
        var lookup = f.Service.Handle(f.Request(input, RequestKinds.Receipt)).GetAwaiter().GetResult();
        Check(lookup.Status == "not_found" && lookup.Error!.Contains("still be queued") && !task.IsCompleted);
        ExternalEvent.PumpAll(f.Ui); Check(task.Result.State == ReceiptStates.InvocationCompleted);
    }
    private static void DeniedThenDrain()
    {
        using var f = new Fixture(); var input = f.Input(); ExternalEvent.NextRaise = ExternalEventRequest.Denied;
        var denied = f.Queue.Enqueue(f.Work(input)); Check(denied.Result.State == ReceiptStates.RejectedBeforeStart);
        var firstRecord = JsonSerializer.Serialize(f.Journal.GetReceipt(input.OperationId));
        var next = f.Queue.Enqueue(f.Work(f.Input())); ExternalEvent.PumpAll(f.Ui);
        Check(next.Result.State == ReceiptStates.InvocationCompleted && f.Document.Native.Mutations == 1);
        Check(firstRecord == JsonSerializer.Serialize(f.Journal.GetReceipt(input.OperationId)));
        Check(File.ReadAllLines(f.JournalPath).Length == 3);
    }
    private static void DetachedJournal()
    {
        using var f = new Fixture(); var input = f.Input(); f.Journal.TryStart(input, out _);
        var source = Terminal(input); var appended = f.Journal.AppendTerminal(input, source); var bytes = f.Bytes();
        source.Changes!.Added.Clear(); source.Precondition!.Revision = 999;
        appended.Receipt!.Changes!.Added.Add(999); appended.Receipt.Precondition!.DocumentKey = "wrong"; appended.Input = Change(input, document: "wrong");
        var fetched = f.Journal.Get(input.OperationId)!; fetched.Receipt!.State = "wrong"; fetched.Receipt.Changes!.Added.Clear();
        var final = f.Journal.GetReceipt(input.OperationId)!;
        Check(final.State == ReceiptStates.InvocationCompleted && final.Changes!.Added.SequenceEqual(new long[] { 7 }));
        Check(final.Precondition!.Revision == input.Revision && final.Precondition.DocumentKey == input.DocumentKey && f.Bytes() == bytes);
    }
    private static void DeniedAfterStart()
    {
        using var f = new Fixture(); var input = f.Input(); f.Journal.TryStart(input, out _); var bytes = f.Bytes();
        ExternalEvent.NextRaise = ExternalEventRequest.Denied;
        var receipt = f.Queue.Enqueue(f.Work(input)).GetAwaiter().GetResult();
        Check(receipt.State == ReceiptStates.RunningUnknown && receipt.Started && !receipt.MayRetry);
        Check(f.Bytes() == bytes && f.Journal.IsHealthy && f.Document.Native.Mutations == 0);
    }
    private static void StaleContext()
    {
        foreach (var change in new Action<Fixture>[] {
            f => f.Ui.Application.Changed(f.Document),
            f => f.Document.ActiveView.Id = new ElementId(99),
            f => f.Ui.ActiveUIDocument.Selection.Ids.Add(new ElementId(99)),
            f => f.Ui.ActiveUIDocument = new UIDocument(new Document(new NativeDocument())),
            f => f.Ui.ActiveUIDocument = null! })
        {
            using var f = new Fixture(); var input = f.Input(); var task = f.Queue.Enqueue(f.Work(input)); change(f);
            ExternalEvent.PumpAll(f.Ui); var receipt = task.GetAwaiter().GetResult();
            Check(receipt.State == ReceiptStates.ContextChangedBeforeStart && !receipt.Started);
            Check(f.Document.Native.Mutations == 0 && File.ReadAllLines(f.JournalPath).Length == 1);
        }
    }
    private static void DeniedUnhealthy()
    {
        using var f = new Fixture(FaultAt(2, false)); var input = f.Input(); f.Run(input); var bytes = f.Bytes();
        Check(!f.Journal.IsHealthy && f.Document.Native.Mutations == 1);
        ExternalEvent.NextRaise = ExternalEventRequest.Denied;
        var denied = f.Queue.Enqueue(f.Work(input)).GetAwaiter().GetResult();
        Check(denied.State == ReceiptStates.RunningUnknown && denied.Started && !denied.MayRetry);
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 1);
    }
    private static void FirstTerminal()
    {
        using var f = new Fixture(); var input = f.Input(); f.Journal.TryStart(input, out _);
        var original = f.Journal.AppendTerminal(input, Terminal(input)); var bytes = f.Bytes();
        var next = f.Journal.AppendTerminal(input, Terminal(input, "999"));
        Check(next.Receipt!.ResultJson == "42" && next.TimestampUtc == original.TimestampUtc && f.Bytes() == bytes);
        Throws<JournalBindingException>(() => f.Journal.AppendTerminal(Change(input, document: "wrong"), Terminal(Change(input, document: "wrong"))));
        Check(f.Bytes() == bytes && f.Journal.IsHealthy);
    }
    private static void LegacyArchive()
    {
        using var f = new Fixture(); var legacy = f.Input();
        foreach (var version in new[] { 0, 3 })
        {
            var archival = JsonSerializer.Serialize(new { SchemaVersion = version, OperationId = legacy.OperationId,
                SourceSha256 = legacy.SourceSha256, DocumentKey = legacy.DocumentKey, Phase = "terminal",
                Input = version == 3 ? new { legacy.OperationId, legacy.SourceSha256, legacy.DocumentKey, legacy.Revision, legacy.ActiveViewId, legacy.SelectionDigest } : null,
                Receipt = new { state = "invocation_completed" }, TimestampUtc = "old" }) + "\n";
            File.WriteAllText(f.JournalPath, archival); var journal = new OperationJournal(f.JournalPath);
            Check(journal.IsHealthy && !journal.Get(legacy.OperationId)!.IsBound && journal.GetReceipt(legacy.OperationId) == null);
            Check(journal.Get(legacy.OperationId)!.Input == null && journal.Get(legacy.OperationId)!.ArchiveJson == archival.TrimEnd());
            Check(Throws<JournalBindingException>(() => journal.TryStart(f.Input(), out _)).Status == ReceiptStates.LegacyUnbound);
            var owned = new OperationJournal(f.JournalPath, f.Target);
            Check(!owned.IsHealthy && owned.FailureStatus == ReceiptStates.LegacyUnbound);
            Check(f.Bytes() == archival);
        }
    }
    private static void LookupFailures()
    {
        using var f = new Fixture(); var request = f.Request(f.Input(), RequestKinds.Receipt); request.OperationId = "invalid";
        Check(f.Service.Handle(request).GetAwaiter().GetResult().Status == "invalid_request");
        File.WriteAllText(f.JournalPath, "broken"); var journal = new OperationJournal(f.JournalPath, f.Target); Check(!journal.IsHealthy);
        request.OperationId = Guid.NewGuid().ToString();
        Check(f.CreateService(journal).Handle(request).GetAwaiter().GetResult().Status == "journal_unavailable");
        request.Kind = RequestKinds.Execute;
        Check(f.CreateService(journal).Handle(request).GetAwaiter().GetResult().Status == "journal_unavailable");
    }
    private static Action<string, byte[]> FaultAt(int call, bool whole)
    {
        var count = 0;
        return (path, bytes) =>
        {
            count++; using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
            stream.Write(bytes, 0, count == call && !whole ? bytes.Length / 2 : bytes.Length); stream.Flush(true);
            if (count == call) throw new IOException("injected failure after file write");
        };
    }
    private static void PartialStart() => StartFailure(false);
    private static void CompleteStartFailure() => StartFailure(true);
    private static void StartFailure(bool whole)
    {
        using var f = new Fixture(FaultAt(1, whole)); var input = f.Input(); var receipt = f.Run(input);
        Check(!f.Journal.IsHealthy && f.Document.Native.Mutations == 0 && !receipt.MayRetry);
        Throws<IOException>(() => f.Journal.Get(input.OperationId));
        Throws<IOException>(() => f.Journal.TryStart(f.Input(), out _));
        var restarted = new OperationJournal(f.JournalPath, f.Target); Check(restarted.IsHealthy == whole);
        if (whole)
        {
            var lookup = f.CreateService(restarted).Handle(f.Request(input, RequestKinds.Receipt)).GetAwaiter().GetResult();
            Check(lookup.Status == ReceiptStates.RunningUnknown);
        }
    }
    private static void PartialTerminal() => TerminalFailure(false);
    private static void CompleteTerminalFailure() => TerminalFailure(true);
    private static void TerminalFailure(bool whole)
    {
        using var f = new Fixture(FaultAt(2, whole)); var input = f.Input(); var receipt = f.Run(input);
        Check(!f.Journal.IsHealthy && f.Document.Native.Mutations == 1);
        Check(receipt.State == ReceiptStates.RunningUnknown && receipt.Started && !receipt.MayRetry);
        var again = f.Run(f.Input()); Check(again.State == ReceiptStates.RunningUnknown && f.Document.Native.Mutations == 1);
        var restarted = new OperationJournal(f.JournalPath, f.Target); Check(restarted.IsHealthy == whole);
        if (whole)
        {
            var original = restarted.GetReceipt(input.OperationId)!;
            Check(original.State == ReceiptStates.InvocationCompleted);
            Check(new ExecutionEngine(f.Collector, restarted).Execute(f.Ui, f.Work(input)).TimestampUtc == original.TimestampUtc);
            Check(f.Document.Native.Mutations == 1);
        }
    }
    private static void CorruptJournal()
    {
        using var f = new Fixture(); var input = f.Input(); f.Run(input); var lines = File.ReadAllLines(f.JournalPath);
        var corruptions = new List<string>();
        void ChangeStart(Action<JsonObject> edit)
        { var root = JsonNode.Parse(lines[0])!.AsObject(); edit(root); corruptions.Add(root.ToJsonString() + "\n"); }
        ChangeStart(root => root["SchemaVersion"] = 99);
        ChangeStart(root => root["Input"]!.AsObject().Remove("Revision"));
        ChangeStart(root => root["Input"]!.AsObject().Remove("Target"));
        ChangeStart(root => root["Input"]!["Target"] = null);
        ChangeStart(root => root["Input"]!["Target"]!["instance_id"] = Guid.NewGuid().ToString("D"));
        ChangeStart(root => root["Input"]!["Target"]!["journal_id"] = Guid.NewGuid().ToString("D"));
        ChangeStart(root => root["Input"]!["Target"]!["revit_version"] = "2023");
        ChangeStart(root => root["Input"]!["Revision"] = -1);
        ChangeStart(root => root["Input"]!["unknown"] = true);
        ChangeStart(root => root["DocumentKey"] = "different");
        ChangeStart(root => root["Phase"] = "unknown");
        corruptions.Add(lines[0].Replace("\"SchemaVersion\":4", "\"SchemaVersion\":4,\"SchemaVersion\":4") + "\n");
        corruptions.Add(lines[0].Replace(input.DocumentKey, "doc-\\uD800") + "\n"); // Escaped lone surrogate is not a repaired identity.
        corruptions.Add(lines[1] + "\n"); // terminal without durable start
        corruptions.Add(lines[0] + "\n" + lines[0] + "\n"); // duplicate start
        corruptions.Add(string.Join("\n", lines) + "\n" + lines[1] + "\n"); // duplicate terminal
        var changed = JsonNode.Parse(lines[1])!.AsObject(); changed["Input"]!["Revision"] = 77;
        changed["Receipt"]!["precondition"]!["revision"] = 77;
        corruptions.Add(lines[0] + "\n" + changed.ToJsonString() + "\n");
        var receiptTarget = JsonNode.Parse(lines[1])!.AsObject(); receiptTarget["Receipt"]!["target"]!["journal_id"] = Guid.NewGuid().ToString("D");
        corruptions.Add(lines[0] + "\n" + receiptTarget.ToJsonString() + "\n");
        foreach (var text in corruptions)
        {
            File.WriteAllText(f.JournalPath, text); var broken = new OperationJournal(f.JournalPath, f.Target);
            Check(!broken.IsHealthy, "accepted corrupt fixture: " + text);
            Throws<IOException>(() => broken.Get(input.OperationId)); Check(f.Bytes() == text);
        }
    }
    private static void UnterminatedRecord()
    {
        var calls = 0;
        using var f = new Fixture((path, bytes) =>
        {
            calls++; using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
            var count = calls == 2 ? bytes.Length - Encoding.UTF8.GetByteCount(Environment.NewLine) : bytes.Length;
            stream.Write(bytes, 0, count); stream.Flush(true);
            if (calls == 2) throw new IOException("complete JSON written but delimiter lost");
        });
        var input = f.Input(); var result = f.Run(input); var original = f.Bytes();
        Check(result.State == ReceiptStates.RunningUnknown && result.Started && !result.MayRetry
              && f.Document.Native.Mutations == 1);
        Check(!original.EndsWith("\n", StringComparison.Ordinal));
        var recovered = new OperationJournal(f.JournalPath, f.Target);
        if (recovered.IsHealthy)
        {
            // Keep the full historical counterexample executable: accepting
            // this tail glues the next JSON object onto the previous record.
            recovered.TryStart(f.Input(), out _);
            var later = new OperationJournal(f.JournalPath, f.Target);
            throw new Exception("accepted undelimited JSON; after another append restart healthy=" + later.IsHealthy);
        }
        Check(f.Bytes() == original);
        Throws<IOException>(() => recovered.TryStart(f.Input(), out _));
    }

    private static void InvalidJournalUtf8()
    {
        using var f = new Fixture(); var input = Change(f.Input(), document: "doc-X");
        Check(f.Journal.TryStart(input, out _));
        var bytes = File.ReadAllBytes(f.JournalPath).Select(b => b == (byte)'X' ? (byte)0xFF : b).ToArray();
        Check(bytes.Count(b => b == 0xFF) == 2);
        Throws<DecoderFallbackException>(() => new UTF8Encoding(false, true).GetString(bytes));
        File.WriteAllBytes(f.JournalPath, bytes);
        var recovered = new OperationJournal(f.JournalPath, f.Target);
        Check(!recovered.IsHealthy, "accepted malformed UTF8 and changed document identity through replacement fallback");
        Throws<IOException>(() => recovered.Get(input.OperationId));
        Throws<IOException>(() => recovered.TryStart(f.Input(), out _));
        Check(File.ReadAllBytes(f.JournalPath).SequenceEqual(bytes));
    }

    private static void JournalBom()
    {
        using var f = new Fixture(); var input = f.Input(); Check(f.Journal.TryStart(input, out _)); var json = f.Bytes();
        foreach (var encoding in new Encoding[] { new UnicodeEncoding(true, true, true), new UnicodeEncoding(false, true, true),
            new UTF32Encoding(true, true, true), new UTF8Encoding(true, true) })
        {
            var bytes = encoding.GetPreamble().Concat(encoding.GetBytes(json)).ToArray(); File.WriteAllBytes(f.JournalPath, bytes);
            var recovered = new OperationJournal(f.JournalPath, f.Target);
            Check(!recovered.IsHealthy, "auto-converted journal encoding " + encoding.WebName);
            Throws<IOException>(() => recovered.TryStart(f.Input(), out _));
            Check(File.ReadAllBytes(f.JournalPath).SequenceEqual(bytes));
        }
    }

    private static void UnicodeJournal()
    {
        using var f = new Fixture(); var input = Change(f.Input(), document: "doc-Привет-😀-\uFFFD");
        Check(f.Journal.TryStart(input, out _));
        // Literal UTF8, not only JSON escapes: valid U+FFFD is itself legal data.
        var line = JsonSerializer.Serialize(f.Journal.Get(input.OperationId), new JsonSerializerOptions {
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
        File.WriteAllBytes(f.JournalPath, new UTF8Encoding(false, true).GetBytes(line + "\n"));
        var recovered = new OperationJournal(f.JournalPath, f.Target);
        Check(recovered.IsHealthy && recovered.Get(input.OperationId)!.Input!.Matches(input));
    }
    private static void ContextRoute()
    {
        using var f = new Fixture(); var input = f.Input(); var request = f.Request(input, RequestKinds.Context);
        var task = f.Service.Handle(request); Check(!task.IsCompleted); ExternalEvent.PumpAll(f.Ui);
        var response = task.GetAwaiter().GetResult();
        Check(response.Ok && response.Context!.Complete && response.Context.DocumentKey == input.DocumentKey && response.Context.Revision == input.Revision);
    }
}
