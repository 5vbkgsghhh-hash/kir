using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
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
using Kir.Revit.Connector.Transport;
using Kir.Revit.PipeClient;
using Kir.Revit.Protocol;

internal static class PipeClientTests
{
    private static readonly (string, Func<Task>)[] Cases =
    {
        ("raw external frames preserve Unicode and remain capped at16 MiB", RawBytes),
        ("wrong server PID sends no token or source bytes", WrongPid),
        ("unavailable PID probe sends no token or source bytes", FailedPid),
        ("client closes after exactly one response without server EOF", ResponseBeforeEof),
        ("partial response is cancelled by the shared deadline", PartialResponse),
        ("absent local pipe expires without retry", Absent),
        ("production command has no non-Windows PID bypass", Unsupported),
    };
    public static async Task<int> Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "exchange") return await PortableHelper(args);
        if (args.Length > 0 && args[0] == "--server") return Server(args[1], args[2], args[3]);
        var failed = 0;
        foreach (var test in Cases)
        {
            try { await test.Item2(); Console.WriteLine("PASS " + test.Item1); }
            catch (Exception error) { failed++; Console.Error.WriteLine("FAIL " + test.Item1 + ": " + error); }
        }
        Console.WriteLine($"{Cases.Length - failed} passed, {failed} failed; portable pipes, injected PID probe, no Windows identity proof");
        return failed == 0 ? 0 : 1;
    }
    private static void Check(bool value, string message = "assertion failed") { if (!value) throw new Exception(message); }
    private static byte[] Request() => JsonSerializer.SerializeToUtf8Bytes(new ConnectorRequest
    {
        Protocol = ProtocolConstants.Version, RequestId = "request", Kind = RequestKinds.Ping, Token = "secret-source",
        SessionId = Guid.NewGuid().ToString("D"), Target = Target("2026"),
    });
    private static ConnectorTarget Target(string year) => new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"), year);
    private static NamedPipeServerStream Pipe(string name) => new NamedPipeServerStream(name, PipeDirection.InOut, 1,
        PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
    private static Task<byte[]> Run(byte[] request, string name, CancellationToken token, Func<Microsoft.Win32.SafeHandles.SafePipeHandle, uint>? probe = null) =>
        Exchange.Run(request, name, 123, token, probe ?? (_ => 123), (_, _) => { });
    private static async Task RawBytes()
    {
        var raw = Encoding.UTF8.GetBytes("{\"text\":\"Ж😀\", \"n\":1}");
        using var stream = new MemoryStream(); await JsonFraming.WriteRawAsync(stream, raw, CancellationToken.None); stream.Position = 0;
        Check((await JsonFraming.ReadRawAsync(stream, CancellationToken.None)).SequenceEqual(raw));
        foreach (var bad in new[] { Array.Empty<byte>(), Encoding.UTF8.GetBytes("{\"x\":1,\"x\":2}"), new byte[] { 0xff }, new byte[ProtocolConstants.MaxFrameBytes + 1] })
        {
            var refused = false;
            try { await JsonFraming.WriteRawAsync(new MemoryStream(), bad, CancellationToken.None); } catch { refused = true; }
            Check(refused);
        }
    }
    private static async Task Identity(bool throwProbe)
    {
        var name = "kir-pid-" + Guid.NewGuid().ToString("N"); using var server = Pipe(name); using var stop = new CancellationTokenSource(5000);
        var waiting = server.WaitForConnectionAsync(stop.Token);
        var exchange = Run(Request(), name, stop.Token, _ => throwProbe ? throw new IOException() : 999u);
        await waiting; var read = server.ReadAsync(new byte[1], 0, 1, stop.Token);
        var failed = false;
        try { await exchange; } catch (ClientFailure error) { failed = error.Code == (throwProbe ? "server_identity_unavailable" : "server_pid_mismatch"); }
        Check(failed && await read == 0, "request bytes escaped before PID approval");
    }
    private static Task WrongPid() => Identity(false);
    private static Task FailedPid() => Identity(true);
    private static async Task ResponseBeforeEof()
    {
        var name = "kir-one-shot-" + Guid.NewGuid().ToString("N"); using var server = Pipe(name); using var stop = new CancellationTokenSource(5000);
        var waiting = server.WaitForConnectionAsync(stop.Token); var exchange = Run(Request(), name, stop.Token);
        await waiting; await JsonFraming.ReadRawAsync(server, stop.Token);
        var response = Encoding.UTF8.GetBytes("{\"status\":\"fixture\",\"unicode\":\"Ж😀\"}");
        await JsonFraming.WriteRawAsync(server, response, stop.Token);
        Check((await exchange).SequenceEqual(response)); // Server has not closed.
        Check(await server.ReadAsync(new byte[1], 0, 1, stop.Token) == 0);
    }
    private static async Task PartialResponse()
    {
        var name = "kir-partial-client-" + Guid.NewGuid().ToString("N"); using var server = Pipe(name); using var stop = new CancellationTokenSource(300);
        var waiting = server.WaitForConnectionAsync(stop.Token); var exchange = Run(Request(), name, stop.Token);
        await waiting; await JsonFraming.ReadRawAsync(server, stop.Token); server.Write(BitConverter.GetBytes(100)); server.WriteByte((byte)'{'); server.Flush();
        var refused = false; try { await exchange; } catch (OperationCanceledException) { refused = true; } Check(refused);
    }
    private static async Task Absent()
    {
        using var stop = new CancellationTokenSource(100); var refused = false;
        try { await Run(Request(), "kir-absent-" + Guid.NewGuid().ToString("N"), stop.Token); } catch (OperationCanceledException) { refused = true; }
        Check(refused);
    }
    private static async Task Unsupported()
    {
        if (OperatingSystem.IsWindows()) return;
        var result = await Kir.Revit.PipeClient.Program.Main(new[] { "exchange", "--pipe", "missing", "--expected-server-pid", "123", "--timeout-ms", "1000" });
        Check(result != 0);
    }

    // This is a test executable, not a production CLI flag. It replaces only
    // Windows PID inspection; same-user pipes and exact frame transfer are real.
    private static async Task<int> PortableHelper(string[] args)
    {
        var options = Options.Parse(args); var mode = Environment.GetEnvironmentVariable("KIR_PIPE_TEST_HELPER_MODE");
        var pidPath = Environment.GetEnvironmentVariable("KIR_PIPE_TEST_PID_FILE");
        if (pidPath != null) File.WriteAllText(pidPath, Process.GetCurrentProcess().Id.ToString());
        if (mode == "production_cli") return await Kir.Revit.PipeClient.Program.Main(args);
        if (mode == "diagnostic" || mode == "diagnostic_exit0" || mode == "diagnostic_exit7")
        {
            await Exchange.ReadInput(Console.OpenStandardInput(), CancellationToken.None);
            Console.Error.Write(Environment.GetEnvironmentVariable("KIR_PIPE_TEST_DIAGNOSTIC"));
            Console.Write("{}"); // Even a response-looking stdout is not accepted on exit2.
            return mode == "diagnostic_exit0" ? 0 : mode == "diagnostic_exit7" ? 7 : 2;
        }
        if (mode == "hang") { await Task.Delay(Timeout.Infinite); return 9; }
        if (mode == "oversize") { Console.OpenStandardOutput().Write(new byte[ProtocolConstants.MaxFrameBytes + 1]); return 0; }
        if (mode == "stderr_flood") { Console.Error.Write(new string('e', 1024 * 1024)); return 0; }
        if (mode == "duplicate") { Console.Write("{\"x\":1,\"x\":2}"); return 0; }
        if (mode == "extra_json") { Console.Write("{}{}"); return 0; }
        if (mode == "abnormal") { Console.Write("{}"); return 7; }
        if (mode == "stderr_success") { Console.Error.Write("failure"); Console.Write("{}"); return 0; }
        try
        {
            using var deadline = new CancellationTokenSource(options.TimeoutMs);
            var request = await Exchange.ReadInput(Console.OpenStandardInput(), deadline.Token);
            var response = await Exchange.Run(request, options.PipeName, options.ExpectedPid, deadline.Token,
                _ => mode == "wrong_pid" ? 0 : (uint)options.ExpectedPid, (_, _) => { });
            await Console.OpenStandardOutput().WriteAsync(response); return 0;
        }
        catch { Console.Error.WriteLine("{\"fixture_failure\":true}"); return 2; }
    }

    private static int Server(string root, string year, string mode)
    {
        Directory.CreateDirectory(root); var target = Target(year);
        var ui = new UIApplication(); ui.Application.VersionNumber = year;
        var document = new Document(new NativeDocument { Title = "Pilot fixture Ж😀" }); ui.ActiveUIDocument = new UIDocument(document);
        using var tracker = new DocumentRevisionTracker(ui.Application);
        using var owner = JournalOwner.CreateNew(root, target);
        var collector = new ContextSnapshotCollector(tracker); using var context = new ContextQueryScheduler(collector);
        using var execution = new ExternalEventScheduler(new ExecutionEngine(collector, owner.Journal));
        var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddHours(1));
        var service = new ConnectorService("fixture-token-Ж😀", admission, context, execution, new CompilerHostClient(root), owner.Journal, target, root);
        var record = new DiscoveryRecord { Target = target, SessionId = admission.SessionId,
            PipeName = "kir-fixture-" + Guid.NewGuid().ToString("N"), ProcessId = Process.GetCurrentProcess().Id,
            Token = "fixture-token-Ж😀", ExpiresUtc = admission.ExpiresUtc.ToString("O", CultureInfo.InvariantCulture) };
        using var stop = new CancellationTokenSource();
        NamedPipeHost? host = null; NamedPipeServerStream? raw = null;
        try
        {
            if (mode == "raw")
            {
                raw = Pipe(record.PipeName); var server = raw;
                _ = Task.Run(async () =>
                {
                    while (!stop.IsCancellationRequested)
                    {
                        await server.WaitForConnectionAsync(stop.Token);
                        var request = await JsonFraming.ReadRawAsync(server, stop.Token);
                        File.WriteAllText(Path.Combine(root, "request.sha256"), Convert.ToHexString(SHA256.HashData(request)).ToLowerInvariant());
                        await JsonFraming.WriteRawAsync(server, Encoding.UTF8.GetBytes("{\"fixture\":\"raw_echo_not_execution\"}"), stop.Token);
                        await server.ReadAsync(new byte[1], 0, 1, stop.Token); server.Disconnect();
                    }
                });
            }
            else
            {
                host = new NamedPipeHost(record.PipeName, request =>
                {
                    File.AppendAllText(Path.Combine(root, "requests"), request.Kind + "\n");
                    if (mode == "seeded" && request.Kind == RequestKinds.Execute && request.Target!.Matches(target)
                        && request.SessionId == record.SessionId && request.Token == record.Token)
                    {
                        var input = OperationInputBinding.Capture(request.OperationId!, request.SourceSha256!, request.Precondition!, target);
                        if (owner.Journal.Get(input.OperationId) == null)
                        {
                            owner.Journal.TryStart(input, out _);
                            owner.Journal.AppendTerminal(input, new OperationReceipt { Target = target, OperationId = input.OperationId,
                                SourceSha256 = input.SourceSha256, DocumentKey = input.DocumentKey, Precondition = input.ToPrecondition(),
                                State = ReceiptStates.InvocationCompleted, Started = true, MayRetry = false,
                                TransactionEvidence = "changes_not_observed", Changes = new ChangeManifest(),
                                // Optional test-provided synthetic result; never
                                // inferred from C# or claimed as a native effect.
                                ResultJson = File.Exists(Path.Combine(root, "seed-result.json"))
                                    ? File.ReadAllText(Path.Combine(root, "seed-result.json"))
                                    : "{\"ok\":true,\"L\":{\"id\":\"700\"}}", TimestampUtc = DateTime.UtcNow.ToString("O") });
                        }
                    }
                    return service.Handle(request);
                });
                host.Start();
            }
            using var discovery = new DiscoveryFile(root, record, path => Directory.CreateDirectory(path));
            Console.WriteLine(JsonSerializer.Serialize(new { discovery = discovery.Path, scope = "portable_pid_injection_seeded_receipts_not_invocation" }));
            while (!File.Exists(Path.Combine(root, "stop"))) { ExternalEvent.PumpAll(ui); Thread.Sleep(5); }
            return 0;
        }
        finally { admission.Close(); stop.Cancel(); host?.Dispose(); raw?.Dispose(); }
    }
}
