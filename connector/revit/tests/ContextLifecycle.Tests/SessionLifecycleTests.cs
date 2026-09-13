using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Connector;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Connector.Transport;
using Kir.Revit.Protocol;

internal static class SessionLifecycleTests
{
    public static readonly (string Name, Action Run)[] Cases =
    {
        ("session admission validates canonical identity and future UTC expiry", AdmissionIdentity),
        ("closed session cancels queued work before durable start", CloseBeforeStart),
        ("expired admission cannot start even if no timer callback runs", ExpiredBeforeStart),
        ("session close after durable start does not interrupt invocation", CloseAfterStart),
        ("durable start and session close share one linearization gate", StartCloseRace),
        ("closed authenticated service preserves prior evidence but rejects fresh work", ClosedEvidence),
        ("new transport session can retrieve original binding without executing", NewSessionEvidence),
        ("disposed context scheduler settles pending work without late native capture", ContextShutdown),
        ("runtime shutdown settles queued work before releasing journal ownership", AppShutdownQueue),
        ("reentrant shutdown retains owner until admitted invocation completes", ReentrantShutdown),
        ("listener binds before discovery publication and bind failure publishes nothing", PublicationOrder),
        ("discovery publication failure closes admission and listener", PublicationFailure),
        ("discovery must match exact service target token session and expiry", DiscoveryBinding),
        ("separate discovery files coexist and old cleanup preserves new session", DiscoveryOwnership),
        ("discovery cleanup preserves replaced bytes and creation never overwrites", DiscoveryReplacement),
        ("actual App derives native year and keeps one owner through session toggles", AppBootstrap),
        ("actual App refuses unsupported native year before creating files", UnsupportedYear),
        ("stale expiry callback cannot close a newer actual App session", StaleTimer),
        ("expiry during session construction cannot publish a ready App session", ImmediateTimer),
        ("App enable binding failure leaves no ready discovery or open session", AppBindFailure),
        ("actual portable pipe is connectable when Start returns", ActualPipe),
        ("actual portable pipe accepts reconnects after abandoned and invalid frames", PipeReconnect),
        ("disposing actual portable pipe interrupts an incomplete frame read", PartialFrameShutdown),
        ("disposing actual portable pipe cancels a blocked response write", BlockedWriteShutdown),
        ("disposing actual portable pipe cancels response EOF wait", EofShutdown),
        ("connection read timeout is named and does not invoke the handler", ReadTimeout),
        ("client EOF timeout frees the route for the next connection", EofTimeout),
        ("connection idle timer does not time out an awaited operation", AwaitedOperation),
        ("sync and async framing share exact bytes bounds and strict JSON", AsyncFraming),
        ("independent App processes publish separate routes without clobber", AppProcesses),
        ("crashed App discovery is stale evidence not ownership of a new runtime", AppCrash),
    };

    private static void Check(bool value, string message = "assertion failed") { if (!value) throw new Exception(message); }
    private static T Throws<T>(Action action) where T : Exception
    { try { action(); } catch (T error) { return error; } throw new Exception("expected " + typeof(T).Name); }
    private static void Ready(Task task) => Check(task.Wait(TimeSpan.FromSeconds(10)), "task timed out");
    private static T Field<T>(object instance, string field) => (T)instance.GetType().GetField(field, BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(instance)!;
    private static void Prepare(string directory) => Directory.CreateDirectory(directory);
    private sealed class Temp : IDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "kir-session-test-" + Guid.NewGuid().ToString("N"));
        public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }
    private sealed class Resource : IDisposable
    {
        public bool Disposed { get; private set; }
        public void Dispose() { Disposed = true; }
    }
    private sealed class Listener : IConnectorListener
    {
        public bool Started { get; private set; }
        public bool Disposed { get; private set; }
        public bool Fail { get; set; }
        public void Start() { if (Fail) throw new IOException("test bind failure"); Started = true; }
        public void Dispose() { Disposed = true; }
    }
    private static DiscoveryRecord Record(ConnectorService service) => new DiscoveryRecord
    {
        Target = service.Target, SessionId = service.Admission.SessionId, Token = "token",
        PipeName = "kir-test-" + Guid.NewGuid().ToString("N"), ProcessId = Process.GetCurrentProcess().Id,
        ExpiresUtc = service.Admission.ExpiresUtc.ToString("O", CultureInfo.InvariantCulture),
    };
    private static string DiscoveryPath(string root, DiscoveryRecord record) =>
        Path.Combine(root, "discovery", record.Target!.InstanceId, record.SessionId + ".json");

    private static void AdmissionIdentity()
    {
        var id = Guid.NewGuid(); var now = DateTime.UtcNow;
        var admission = new SessionAdmission(id.ToString("B").ToUpperInvariant(), now.AddMinutes(1), () => now);
        Check(admission.SessionId == id.ToString("D") && admission.IsOpen);
        foreach (var invalid in new[] { "", "../unsafe", Guid.Empty.ToString("D") })
            Throws<ArgumentException>(() => new SessionAdmission(invalid, now.AddMinutes(1)));
        foreach (var expiry in new[] { now, now.AddSeconds(-1), DateTime.SpecifyKind(now.AddHours(1), DateTimeKind.Unspecified), now.AddHours(1).ToLocalTime() })
            Throws<ArgumentException>(() => new SessionAdmission(id.ToString("D"), expiry, () => now));
        admission.Close(); admission.Close(); Check(!admission.IsOpen);
    }
    private static void CloseBeforeStart()
    {
        using var f = new ExecutionBindingTests.Fixture(); var input = f.Input(); var task = f.Queue.Enqueue(f.Work(input));
        f.Admission.Close(); ExternalEvent.PumpAll(f.Ui); var receipt = task.GetAwaiter().GetResult();
        Check(receipt.State == ReceiptStates.CancelledBeforeStart && !receipt.Started && receipt.MayRetry);
        Check(f.Document.Native.Mutations == 0 && f.Journal.Get(input.OperationId)!.Receipt!.State == ReceiptStates.CancelledBeforeStart);
        Check(!f.Bytes().Contains("\"Phase\":\"started\""));
    }
    private static void ExpiredBeforeStart()
    {
        using var f = new ExecutionBindingTests.Fixture(); var now = DateTime.UtcNow;
        var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), now.AddSeconds(1), () => now);
        var input = f.Input(); var task = f.Queue.Enqueue(new ExecutionWorkItem(input, f.Work(input).AssemblyBytes, admission));
        now = now.AddSeconds(2); ExternalEvent.PumpAll(f.Ui);
        Check(task.Result.State == ReceiptStates.CancelledBeforeStart && f.Document.Native.Mutations == 0);
    }
    private static void CloseAfterStart()
    {
        using var f = new ExecutionBindingTests.Fixture(); var input = f.Input();
        f.Document.MutationHook = () => { Check(f.Journal.Get(input.OperationId)!.Receipt == null); f.Admission.Close(); };
        var receipt = f.Run(input);
        Check(receipt.State == ReceiptStates.InvocationCompleted && receipt.Started && !receipt.MayRetry && f.Document.Native.Mutations == 1);
    }
    private static void StartCloseRace()
    {
        using var f = new ExecutionBindingTests.Fixture(); using var entered = new ManualResetEventSlim(); using var release = new ManualResetEventSlim();
        using var closing = new ManualResetEventSlim(); using var closed = new ManualResetEventSlim();
        var path = Path.Combine(f.DirectoryPath, "race.jsonl");
        var journal = new OperationJournal(path, (p, bytes) => { entered.Set(); Check(release.Wait(10000)); OperationJournal.AppendDurably(p, bytes); }, f.Target);
        var input = f.Input();
        var start = Task.Run(() => f.Admission.TryStart(journal, input, out _, out _));
        Check(entered.Wait(10000));
        var close = Task.Run(() => { closing.Set(); f.Admission.Close(); closed.Set(); });
        Check(closing.Wait(10000)); Check(!closed.Wait(100), "Close escaped while durable append was in progress");
        release.Set(); Ready(start); Ready(close); Check(start.Result && journal.Get(input.OperationId) != null && !f.Admission.IsOpen);
    }
    private static void ClosedEvidence()
    {
        using var f = new ExecutionBindingTests.Fixture(); var input = f.Input(); var old = f.Run(input); var bytes = f.Bytes();
        f.Admission.Close(); f.Ui.ActiveUIDocument = null!;
        foreach (var kind in new[] { RequestKinds.Receipt, RequestKinds.Execute })
        { var response = f.Service.Handle(f.Request(input, kind)).GetAwaiter().GetResult(); Check(response.Receipt!.State == old.State); }
        var fresh = new OperationInputBinding(Guid.NewGuid().ToString("D"), input.SourceSha256, input.DocumentKey, input.Revision, null, null, input.Target);
        Check(f.Service.Handle(f.Request(fresh)).GetAwaiter().GetResult().Status == "disabled");
        Check(f.Service.Handle(f.Request(input, RequestKinds.Context)).GetAwaiter().GetResult().Status == "disabled");
        Check(f.Bytes() == bytes && f.Document.Native.Mutations == 1);
    }
    private static void NewSessionEvidence()
    {
        using var f = new ExecutionBindingTests.Fixture(); var input = f.Input(); f.Run(input); f.Admission.Close();
        var next = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddMinutes(10));
        var service = new ConnectorService("next", next, f.Context, f.Queue, new CompilerHostClient(f.DirectoryPath), f.Journal, f.Target, f.DirectoryPath);
        var request = f.Request(input); request.Token = "next"; request.SessionId = next.SessionId;
        var receipt = service.Handle(request).GetAwaiter().GetResult();
        Check(receipt.Ok && receipt.Receipt!.State == ReceiptStates.InvocationCompleted && receipt.SessionId == next.SessionId);
        Check(f.Document.Native.Mutations == 1 && f.Journal.Get(input.OperationId)!.Input!.Matches(input));
    }
    private static void ContextShutdown()
    {
        using var f = new ExecutionBindingTests.Fixture(); var pending = f.Context.Capture(); f.Context.Dispose(); f.Tracker.Dispose();
        Check(pending.IsCanceled); f.Context.Execute(f.Ui); ExternalEvent.PumpAll(f.Ui);
        Throws<ObjectDisposedException>(() => f.Context.Capture().GetAwaiter().GetResult());
    }

    private sealed class AppFixture : IDisposable
    {
        public readonly App App;
        public readonly UIControlledApplication Ui = new UIControlledApplication();
        public readonly List<DiscoveryRecord> Records = new List<DiscoveryRecord>();
        public readonly List<ConnectorService> Services = new List<ConnectorService>();
        public readonly List<Action> Timers = new List<Action>();
        public bool FailBind;
        public bool ImmediateExpiry;
        public AppFixture(string root, string year = "2026", bool actualPipe = false)
        {
            Ui.ControlledApplication.VersionNumber = year;
            App = new App(root, Prepare, (directory, record, service, expire) =>
            {
                Records.Add(record); Services.Add(service);
                IConnectorListener listener = actualPipe ? new NamedPipeHost(record.PipeName, service.Handle) : new Listener { Fail = FailBind };
                return new ConnectorSession(record, service, expire, listener,
                    () => new DiscoveryFile(directory, record, Prepare),
                    (_, callback) => { Timers.Add(callback); if (ImmediateExpiry) callback(); return new Resource(); });
            });
        }
        public void Start() => Check(App.OnStartup(Ui) == Result.Succeeded);
        public void Dispose() { Check(App.OnShutdown(Ui) == Result.Succeeded); }
    }
    private static OperationInputBinding Input(ConnectorTarget target) => new OperationInputBinding(Guid.NewGuid().ToString("D"), new string('a', 64), "doc", 0, null, null, target);
    private static void AppShutdownQueue()
    {
        using var temp = new Temp(); using var f = new AppFixture(temp.Root); f.Start(); f.App.Enable();
        var owner = Field<JournalOwner>(f.App, "_owner"); var queue = Field<ExternalEventScheduler>(f.App, "_execution");
        var input = Input(owner.Target); var admission = f.Services[0].Admission;
        var task = queue.Enqueue(new ExecutionWorkItem(input, new byte[] { 1 }, admission));
        Check(f.App.OnShutdown(f.Ui) == Result.Succeeded);
        Check(task.Result.State == ReceiptStates.CancelledBeforeStart && owner.Journal.IsHealthy);
        var path = Path.Combine(temp.Root, "journals", owner.Target.JournalId, "operations.jsonl");
        var bytes = File.ReadAllBytes(path);
        var late = queue.Enqueue(new ExecutionWorkItem(Input(owner.Target), new byte[] { 1 }, admission)).Result;
        Check(!late.MayRetry && late.State == ReceiptStates.RunningUnknown && owner.Journal.IsHealthy);
        queue.Execute(new UIApplication()); Check(File.ReadAllBytes(path).SequenceEqual(bytes));
        using var recovery = JournalOwner.OpenRecovery(temp.Root, owner.Target);
        Check(recovery.Get(input.OperationId)!.Receipt!.State == ReceiptStates.CancelledBeforeStart);
    }
    private static void ReentrantShutdown()
    {
        using var temp = new Temp(); using var app = new AppFixture(temp.Root); app.Start(); app.App.Enable();
        using var f = new ExecutionBindingTests.Fixture(); var owner = Field<JournalOwner>(app.App, "_owner");
        var queue = Field<ExternalEventScheduler>(app.App, "_execution");
        var collector = Field<ContextSnapshotCollector>(Field<ContextQueryScheduler>(app.App, "_contextQueries"), "_collector");
        var snapshot = collector.Capture(f.Ui); var input = OperationInputBinding.Capture(Guid.NewGuid().ToString("D"), new string('a', 64),
            new ContextPrecondition { DocumentKey = snapshot.DocumentKey, Revision = snapshot.Revision }, owner.Target);
        f.Document.MutationHook = () =>
        {
            Check(app.App.OnShutdown(app.Ui) == Result.Failed);
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, owner.Target)).Status == "journal_lease_unavailable");
        };
        var task = queue.Enqueue(new ExecutionWorkItem(input, f.Work(f.Input()).AssemblyBytes, app.Services[0].Admission));
        ExternalEvent.PumpAll(f.Ui);
        Check(task.Result.State == ReceiptStates.InvocationCompleted && f.Document.Native.Mutations == 1);
        Check(app.App.OnShutdown(app.Ui) == Result.Succeeded);
        using var recovery = JournalOwner.OpenRecovery(temp.Root, owner.Target); Check(recovery.Get(input.OperationId)!.Receipt!.Started);
    }
    private static void PublicationOrder()
    {
        using var f = new ExecutionBindingTests.Fixture(); var pipe = new Listener(); var published = new Resource();
        using (new ConnectorSession(Record(f.Service), f.Service, _ => { }, pipe,
            () => { Check(pipe.Started && !pipe.Disposed); return published; }, (_, _) => new Resource())) { }
        Check(pipe.Disposed && published.Disposed && !f.Admission.IsOpen);
        using var g = new ExecutionBindingTests.Fixture(); var failed = new Listener { Fail = true }; var count = 0;
        Throws<IOException>(() => new ConnectorSession(Record(g.Service), g.Service, _ => { }, failed,
            () => { count++; return new Resource(); }, (_, _) => new Resource()));
        Check(count == 0 && failed.Disposed && !g.Admission.IsOpen);
    }
    private static void PublicationFailure()
    {
        using var f = new ExecutionBindingTests.Fixture(); var pipe = new Listener();
        Throws<IOException>(() => new ConnectorSession(Record(f.Service), f.Service, _ => { }, pipe,
            () => throw new IOException("publication failed"), (_, _) => new Resource()));
        Check(pipe.Started && pipe.Disposed && !f.Admission.IsOpen);
    }
    private static void DiscoveryBinding()
    {
        foreach (var axis in new[] { "token", "session", "target", "expiry", "protocol" })
        {
            using var f = new ExecutionBindingTests.Fixture(); var record = Record(f.Service); var pipe = new Listener();
            if (axis == "token") record.Token += "other";
            if (axis == "session") record.SessionId = Guid.NewGuid().ToString("D");
            if (axis == "target") record.Target = new ConnectorTarget(Guid.NewGuid().ToString("D"), f.Target.InstanceId, "2026");
            if (axis == "expiry") record.ExpiresUtc = DateTime.UtcNow.AddHours(2).ToString("O");
            if (axis == "protocol") record.Protocol = "kir-revit/3";
            Throws<ArgumentException>(() => new ConnectorSession(record, f.Service, _ => { }, pipe, () => new Resource(), (_, _) => new Resource()));
            Check(!pipe.Started && pipe.Disposed && !f.Admission.IsOpen);
        }
    }
    private static void DiscoveryOwnership()
    {
        using var temp = new Temp(); using var f = new ExecutionBindingTests.Fixture(); var a = Record(f.Service); var b = Record(f.Service);
        b.SessionId = Guid.NewGuid().ToString("D");
        var first = new DiscoveryFile(temp.Root, a, Prepare); using var second = new DiscoveryFile(temp.Root, b, Prepare);
        var bytes = File.ReadAllBytes(second.Path); Check(File.Exists(first.Path)); first.Dispose(); first.Dispose();
        Check(!File.Exists(first.Path) && File.ReadAllBytes(second.Path).SequenceEqual(bytes));
    }
    private static void DiscoveryReplacement()
    {
        using var temp = new Temp(); using var f = new ExecutionBindingTests.Fixture(); var record = Record(f.Service);
        var discovery = new DiscoveryFile(temp.Root, record, Prepare); File.WriteAllText(discovery.Path, "replacement");
        discovery.Dispose(); Check(File.ReadAllText(discovery.Path) == "replacement");
        Throws<IOException>(() => new DiscoveryFile(temp.Root, record, Prepare));
        Check(File.ReadAllText(discovery.Path) == "replacement" && Directory.GetFiles(Path.GetDirectoryName(discovery.Path)!).Length == 1);
    }
    private static void AppBootstrap()
    {
        using var temp = new Temp(); Prepare(temp.Root);
        File.WriteAllText(Path.Combine(temp.Root, "operations.jsonl"), "legacy journal");
        File.WriteAllText(Path.Combine(temp.Root, "discovery.json"), "legacy discovery");
        var root = Path.Combine(temp.Root, "v4"); using var f = new AppFixture(root, "2023"); f.Start(); var target = f.App.Target!;
        Check(target.RevitVersion == "2023" && !f.App.IsEnabled); f.App.Enable(); var a = f.Records[0];
        Check(f.App.IsEnabled && File.Exists(DiscoveryPath(root, a)));
        f.App.Disable(); Check(!f.App.IsEnabled && !File.Exists(DiscoveryPath(root, a)));
        Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(root, target)).Status == "journal_lease_unavailable");
        f.App.Enable(); var b = f.Records[1]; Check(b.Target!.Matches(target) && a.SessionId != b.SessionId && a.Token != b.Token && a.PipeName != b.PipeName);
        Check(f.App.OnShutdown(f.Ui) == Result.Succeeded && !File.Exists(DiscoveryPath(root, b)));
        using var recovery = JournalOwner.OpenRecovery(root, target);
        Check(File.ReadAllText(Path.Combine(temp.Root, "operations.jsonl")) == "legacy journal");
        Check(File.ReadAllText(Path.Combine(temp.Root, "discovery.json")) == "legacy discovery");
    }
    private static void UnsupportedYear()
    {
        using var temp = new Temp(); using var f = new AppFixture(temp.Root, "2027");
        Check(f.App.OnStartup(f.Ui) == Result.Failed && !Directory.Exists(temp.Root));
        Throws<InvalidOperationException>(() => f.App.Enable());
    }
    private static void StaleTimer()
    {
        using var temp = new Temp(); using var f = new AppFixture(temp.Root); f.Start(); f.App.Enable(); var first = f.Records[0];
        f.App.Disable(); f.App.Enable(); var second = f.Records[1]; var bytes = File.ReadAllBytes(DiscoveryPath(temp.Root, second));
        f.Timers[0](); Check(f.App.IsEnabled && f.Services[1].Admission.IsOpen);
        Check(!File.Exists(DiscoveryPath(temp.Root, first)) && File.ReadAllBytes(DiscoveryPath(temp.Root, second)).SequenceEqual(bytes));
        f.Timers[1](); Check(!f.App.IsEnabled && !File.Exists(DiscoveryPath(temp.Root, second)));
    }
    private static void AppBindFailure()
    {
        using var temp = new Temp(); using var f = new AppFixture(temp.Root); f.Start(); f.FailBind = true;
        Throws<IOException>(() => f.App.Enable()); Check(!f.App.IsEnabled && !File.Exists(DiscoveryPath(temp.Root, f.Records[0])));
        Check(!f.Services[0].Admission.IsOpen); f.FailBind = false; f.App.Enable(); Check(f.App.IsEnabled);
    }
    private static void ImmediateTimer()
    {
        using var temp = new Temp(); using var f = new AppFixture(temp.Root); f.Start(); f.ImmediateExpiry = true;
        Throws<InvalidOperationException>(() => f.App.Enable());
        Check(!f.App.IsEnabled && !f.Services[0].Admission.IsOpen && !File.Exists(DiscoveryPath(temp.Root, f.Records[0])));
        f.ImmediateExpiry = false; f.App.Enable(); Check(f.App.IsEnabled);
    }
    private static void ActualPipe()
    {
        var name = "kir-portable-" + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeHost(name, request => Task.FromResult(ConnectorResponse.Failure(request.RequestId, "test_reply", "portable")));
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
        client.Connect(5000); JsonFraming.Write(client, new ConnectorRequest { RequestId = "pipe-test" });
        var response = JsonFraming.Read<ConnectorResponse>(client); Check(response.Status == "test_reply" && response.RequestId == "pipe-test");
        pipe.Dispose(); Ready(pipe.Completion);
    }
    private static void PartialFrameShutdown()
    {
        // No pause after the partial write: the accepted-handle/disposal race
        // was independently reproduced on attempt 2 of this interleaving.
        for (var attempt = 0; attempt < 50; attempt++) PartialFrameAttempt();
    }
    private static void PartialFrameAttempt()
    {
        var name = "kir-partial-" + Guid.NewGuid().ToString("N"); var called = 0;
        using var pipe = new NamedPipeHost(name, _ => { Interlocked.Increment(ref called); return Task.FromResult(new ConnectorResponse()); });
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
        client.Connect(5000); var size = BitConverter.GetBytes(100); client.Write(size, 0, size.Length); client.WriteByte((byte)'{'); client.Flush();
        pipe.Dispose(); Ready(pipe.Completion); Check(called == 0);
    }
    private static ConnectorResponse ReadResponse(Stream stream)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        return JsonFraming.ReadAsync<ConnectorResponse>(stream, timeout.Token).GetAwaiter().GetResult();
    }
    private static void BlockedWriteShutdown()
    {
        var name = "kir-blocked-write-" + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeHost(name, _ => Task.FromResult(ConnectorResponse.Failure("large", "large", new string('x', 8 * 1024 * 1024))));
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); client.Connect(5000);
        JsonFraming.Write(client, new ConnectorRequest { RequestId = "large" });
        var prefix = new byte[4];
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var count = client.ReadAsync(prefix, 0, 4, timeout.Token).GetAwaiter().GetResult(); Check(count > 0);
        // The response frame has begun, but the peer never consumes its body.
        pipe.Dispose(); Ready(pipe.Completion);
    }
    private static void EofShutdown()
    {
        var name = "kir-eof-" + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeHost(name, _ => Task.FromResult(ConnectorResponse.Failure("eof", "test_reply", "done")));
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); client.Connect(5000);
        JsonFraming.Write(client, new ConnectorRequest()); Check(ReadResponse(client).Status == "test_reply");
        pipe.Dispose(); Ready(pipe.Completion); // Peer is deliberately still open.
    }
    private static void ReadTimeout()
    {
        var name = "kir-io-timeout-" + Guid.NewGuid().ToString("N"); var calls = 0;
        using var pipe = new NamedPipeHost(name, _ => { calls++; return Task.FromResult(new ConnectorResponse()); }, TimeSpan.FromMilliseconds(100));
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); client.Connect(5000);
        client.WriteByte(10); client.Flush(); var response = ReadResponse(client);
        Check(response.Status == "transport_io_timeout" && response.Error!.Contains("frame_read") && calls == 0);
        pipe.Dispose(); Ready(pipe.Completion);
    }
    private static void EofTimeout()
    {
        var name = "kir-eof-timeout-" + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeHost(name, request => Task.FromResult(ConnectorResponse.Failure(request.RequestId, "test_reply", "done")), TimeSpan.FromMilliseconds(100));
        pipe.Start(); using var old = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); old.Connect(5000);
        JsonFraming.Write(old, new ConnectorRequest { RequestId = "old" }); Check(ReadResponse(old).RequestId == "old");
        // Keep the old peer open: the independent EOF deadline frees its route.
        using var next = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); next.Connect(5000);
        JsonFraming.Write(next, new ConnectorRequest { RequestId = "next" }); Check(ReadResponse(next).RequestId == "next");
        pipe.Dispose(); Ready(pipe.Completion);
    }
    private static void AwaitedOperation()
    {
        var name = "kir-awaited-" + Guid.NewGuid().ToString("N"); using var entered = new ManualResetEventSlim();
        var result = new TaskCompletionSource<ConnectorResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var pipe = new NamedPipeHost(name, _ => { entered.Set(); return result.Task; }, TimeSpan.FromMilliseconds(100));
        pipe.Start(); using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); client.Connect(5000);
        JsonFraming.Write(client, new ConnectorRequest()); Check(entered.Wait(5000));
        Task.Delay(250).GetAwaiter().GetResult(); Check(!pipe.Completion.IsCompleted);
        result.SetResult(ConnectorResponse.Failure("finished", "test_reply", "done"));
        Check(ReadResponse(client).RequestId == "finished"); pipe.Dispose(); Ready(pipe.Completion);
    }
    private static void AsyncFraming()
    {
        var request = new ConnectorRequest { RequestId = "Ж😀", Kind = RequestKinds.Ping };
        using var sync = new MemoryStream(); using var asynchronous = new MemoryStream();
        JsonFraming.Write(sync, request); JsonFraming.WriteAsync(asynchronous, request, CancellationToken.None).GetAwaiter().GetResult();
        Check(sync.ToArray().SequenceEqual(asynchronous.ToArray())); asynchronous.Position = 0;
        Check(JsonFraming.ReadAsync<ConnectorRequest>(asynchronous, CancellationToken.None).GetAwaiter().GetResult().RequestId == request.RequestId);
        foreach (var payload in new[] { System.Text.Encoding.UTF8.GetBytes("{\"kind\":\"ping\",\"kind\":\"execute\"}"), new byte[] { 0xff }, System.Text.Encoding.UTF8.GetBytes("null") })
        {
            using var frame = new MemoryStream(); var size = BitConverter.GetBytes(payload.Length); frame.Write(size, 0, 4); frame.Write(payload, 0, payload.Length);
            frame.Position = 0; Exception? first = null; Exception? second = null;
            try { JsonFraming.Read<ConnectorRequest>(frame); } catch (Exception error) { first = error; }
            frame.Position = 0;
            try { JsonFraming.ReadAsync<ConnectorRequest>(frame, CancellationToken.None).GetAwaiter().GetResult(); } catch (Exception error) { second = error; }
            Check(first != null && second != null && first.GetType() == second.GetType());
        }
        foreach (var length in new[] { 0, -1, ProtocolConstants.MaxFrameBytes + 1 })
        {
            using var frame = new MemoryStream(BitConverter.GetBytes(length));
            Throws<InvalidDataException>(() => JsonFraming.ReadAsync<ConnectorRequest>(frame, CancellationToken.None).GetAwaiter().GetResult());
        }
    }
    private static void PipeReconnect()
    {
        var name = "kir-reconnect-" + Guid.NewGuid().ToString("N");
        using var pipe = new NamedPipeHost(name, request => Task.FromResult(ConnectorResponse.Failure(request.RequestId, "test_reply", "portable")));
        pipe.Start();
        // Abandon a connected request before its frame starts.
        using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous)) client.Connect(5000);
        for (var i = 0; i < 20; i++)
        {
            using var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous); client.Connect(5000);
            if (i % 2 == 0)
            {
                var invalid = BitConverter.GetBytes(-1); client.Write(invalid, 0, invalid.Length); client.Flush();
                Check(Task.Run(() => JsonFraming.Read<ConnectorResponse>(client)).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult().Status == "transport_error");
            }
            else
            {
                JsonFraming.Write(client, new ConnectorRequest { RequestId = i.ToString() });
                var response = Task.Run(() => JsonFraming.Read<ConnectorResponse>(client)).WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
                Check(response.Status == "test_reply" && response.RequestId == i.ToString());
            }
        }
        pipe.Dispose(); Ready(pipe.Completion);
    }

    private static Process StartChild(string root, string year)
    {
        var info = new ProcessStartInfo("dotnet") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (var value in new[] { Assembly.GetExecutingAssembly().Location, "--session-child", root, year }) info.ArgumentList.Add(value);
        return Process.Start(info)!;
    }
    private static DiscoveryRecord ChildRecord(Process child) => JsonSerializer.Deserialize<DiscoveryRecord>(
        child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult()
        ?? throw new Exception(child.StandardError.ReadToEnd()))!;
    private static void Stop(Process child) { if (!child.HasExited) { child.Kill(); Check(child.WaitForExit(10000)); } }
    private static void Ping(DiscoveryRecord record)
    {
        using var client = new NamedPipeClientStream(".", record.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
        client.Connect(5000); JsonFraming.Write(client, new ConnectorRequest
        { Protocol = ProtocolConstants.Version, RequestId = "native-route", Token = record.Token, Target = record.Target, SessionId = record.SessionId, Kind = RequestKinds.Ping });
        var response = JsonFraming.Read<ConnectorResponse>(client);
        Check(response.Status == "ready" && response.Target!.Matches(record.Target) && response.SessionId == record.SessionId);
    }
    private static void AppProcesses()
    {
        using var temp = new Temp(); using var a = StartChild(temp.Root, "2023"); using var b = StartChild(temp.Root, "2026");
        try
        {
            var first = ChildRecord(a); var second = ChildRecord(b);
            Check(first.Target!.RevitVersion == "2023" && second.Target!.RevitVersion == "2026" && !first.Target.Matches(second.Target));
            Ping(first); Ping(second); var bytes = File.ReadAllBytes(DiscoveryPath(temp.Root, second));
            a.StandardInput.WriteLine("exit"); Check(a.WaitForExit(10000) && a.ExitCode == 0);
            Check(!File.Exists(DiscoveryPath(temp.Root, first)) && File.ReadAllBytes(DiscoveryPath(temp.Root, second)).SequenceEqual(bytes));
            Ping(second); using var recovered = JournalOwner.OpenRecovery(temp.Root, first.Target);
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, second.Target!)).Status == "journal_lease_unavailable");
        }
        finally { Stop(a); Stop(b); }
    }
    private static void AppCrash()
    {
        using var temp = new Temp(); using var old = StartChild(temp.Root, "2023");
        Process? next = null;
        try
        {
            var first = ChildRecord(old); old.Kill(); Check(old.WaitForExit(10000));
            var bytes = File.ReadAllBytes(DiscoveryPath(temp.Root, first)); next = StartChild(temp.Root, "2023"); var second = ChildRecord(next);
            Check(!first.Target!.Matches(second.Target) && first.SessionId != second.SessionId && first.PipeName != second.PipeName);
            using var client = new NamedPipeClientStream(".", second.PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
            client.Connect(5000); JsonFraming.Write(client, new ConnectorRequest
            { Protocol = ProtocolConstants.Version, RequestId = "stale", Kind = RequestKinds.Ping, Token = second.Token, SessionId = first.SessionId, Target = first.Target });
            var response = JsonFraming.Read<ConnectorResponse>(client); Check(!response.Ok && response.Status == "target_mismatch");
            client.Dispose(); // One response per connection; close before the next request.
            using var recovery = JournalOwner.OpenRecovery(temp.Root, first.Target);
            Check(File.ReadAllBytes(DiscoveryPath(temp.Root, first)).SequenceEqual(bytes));
            Ping(second);
        }
        finally { Stop(old); if (next != null) { Stop(next); next.Dispose(); } }
    }
    public static int Child(string[] args)
    {
        try
        {
            using var f = new AppFixture(args[1], args[2], actualPipe: true); f.Start(); f.App.Enable();
            Console.WriteLine(JsonSerializer.Serialize(f.Records[0])); Console.ReadLine();
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
