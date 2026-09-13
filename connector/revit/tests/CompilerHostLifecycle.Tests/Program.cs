using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;

internal static class LifecycleTests
{
    private static readonly (string Name, Action Run)[] Cases =
    {
        ("internal capacity preserves full six Mi UTF16 worst-case source", Capacity),
        ("prepared frame detaches source and reference list before launch", Detached),
        ("strict source Unicode and reference limits refuse before process creation", BeforeStart),
        ("internal reader requires exact bounded explicit envelope", InternalReader),
        ("missing executable and throwing reference discovery are named refusals", PreparationErrors),
        ("actual child exchanges complete framed input and successful response", Success),
        ("actual child compile rejection and exit two are preserved", Rejected),
        ("actual production compiler host reads the expanded internal profile", ActualHost),
        ("child refusing stdin cannot outlive write deadline", BlockedInput),
        ("child keeping stdout open cannot outlive overall deadline", BlockedOutput),
        ("explicit cancellation terminates a real child", Cancelled),
        ("stderr flood is continuously drained beyond retained diagnostic limit", StderrFlood),
        ("stderr flood retained in failure is bounded and marked truncated", StderrFailure),
        ("early child exit during request write is cleaned up", EarlyExit),
        ("valid response followed by lingering child is not early success", Linger),
        ("malformed truncated oversized duplicate or trailing stdout fails closed", BadFrames),
        ("exit code and response payload contradictions are refused", Contradictions),
        ("child exception is not a successful compilation", ChildException),
        ("repeated timeout deliveries leave no live child processes", RepeatedTimeout),
    };

    public static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--child") return Child(args[1], args[2]);
        if (args.Length > 0 && args[0] == "--profile") return Profile();
        var failed = 0;
        foreach (var test in Cases)
        {
            try { test.Run(); Console.WriteLine("PASS " + test.Name); }
            catch (Exception error) { failed++; Console.Error.WriteLine("FAIL " + test.Name + ": " + error); }
        }
        Console.WriteLine($"{Cases.Length - failed} passed, {failed} failed; actual local children, no Revit invocation");
        return failed == 0 ? 0 : 1;
    }

    private static void Check(bool value, string message = "assertion failed") { if (!value) throw new Exception(message); }
    private static T Throws<T>(Action action) where T : Exception
    { try { action(); } catch (T error) { return error; } throw new Exception("expected " + typeof(T).Name); }
    private static string Hash(string source) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(source)));
    private static CompilerResponse Positive(string source = "ok") => new CompilerResponse { Ok = true, AssemblyBase64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(Hash(source))) };
    private static CompilerResponse Negative() => new CompilerResponse { Ok = false, Diagnostics = { "fixture_rejected: expected refusal" } };
    private static void Refused(CompilerResponse response, string code)
    { Check(!response.Ok && response.AssemblyBase64 == null && response.Diagnostics.Any(value => value.Contains(code)), string.Join("\n", response.Diagnostics)); }

    private sealed class ChildFixture : IDisposable
    {
        public string DirectoryPath { get; } = Path.Combine(Path.GetTempPath(), "kir-compiler-child-" + Guid.NewGuid().ToString("N"));
        public string PidPath => Path.Combine(DirectoryPath, "child.pid");
        public ChildFixture() { Directory.CreateDirectory(DirectoryPath); }
        public CompilerHostClient Client(string mode, Func<List<string>>? references = null, Action? beforeLaunch = null) => new CompilerHostClient(() =>
        {
            beforeLaunch?.Invoke();
            var start = new ProcessStartInfo("dotnet");
            foreach (var argument in new[] { Assembly.GetExecutingAssembly().Location, "--child", mode, PidPath }) start.ArgumentList.Add(argument);
            return start;
        }, references ?? (() => new List<string>()), minimumTimeoutMs: 100);
        public void Dead()
        {
            Check(File.Exists(PidPath), "child did not record startup");
            var pid = int.Parse(File.ReadAllText(PidPath));
            try { using var process = Process.GetProcessById(pid); Check(process.HasExited, "live orphan child " + pid); }
            catch (ArgumentException) { }
        }
        public void Dispose()
        {
            // Test cleanup is not used to turn a failed no-orphan assertion green.
            if (File.Exists(PidPath))
            {
                try { using var process = Process.GetProcessById(int.Parse(File.ReadAllText(PidPath))); if (!process.HasExited) { process.Kill(); process.WaitForExit(5000); } }
                catch (ArgumentException) { }
            }
            Directory.Delete(DirectoryPath, true);
        }
    }
    private static MemoryStream Frame(string json)
    {
        var bytes = Encoding.UTF8.GetBytes(json); var stream = new MemoryStream();
        stream.Write(BitConverter.GetBytes(bytes.Length)); stream.Write(bytes); stream.Position = 0; return stream;
    }
    private static CompilerRequest Roundtrip(JsonFraming.PreparedCompilerRequest prepared)
    {
        using var stream = new MemoryStream(); prepared.WriteAsync(stream, CancellationToken.None).GetAwaiter().GetResult(); stream.Position = 0;
        return JsonFraming.ReadCompilerRequest(stream);
    }
    private static void Capacity()
    {
        foreach (var text in new[] { new string('Ж', ProtocolConstants.MaxSourceChars), string.Concat(Enumerable.Repeat("😀", ProtocolConstants.MaxSourceChars / 2)) })
        {
            var request = new CompilerRequest { Source = text, ReferencePaths = { "/reference/Ж.dll" } };
            var prepared = JsonFraming.PrepareCompilerRequest(request);
            Check(prepared.PayloadLength > ProtocolConstants.MaxFrameBytes && prepared.PayloadLength <= ProtocolConstants.MaxCompilerRequestFrameBytes);
            Check(Roundtrip(prepared).Source == text);
            using var external = new MemoryStream(); Throws<InvalidDataException>(() => JsonFraming.Write(external, request)); Check(external.Length == 0);
        }
        Check(ProtocolConstants.MaxSourceChars == 6291456 && ProtocolConstants.MaxFrameBytes == 16777216);
    }
    private static void Detached()
    {
        var request = new CompilerRequest { Source = "old Ж", ReferencePaths = { "/old.dll" } };
        var prepared = JsonFraming.PrepareCompilerRequest(request); request.Source = "new"; request.ReferencePaths[0] = "/new.dll";
        var recovered = Roundtrip(prepared); Check(recovered.Source == "old Ж" && recovered.ReferencePaths.Single() == "/old.dll");
        var paths = new List<string> { "/old.dll" }; using var child = new ChildFixture();
        var response = child.Client("reference_echo", () => paths, () => paths[0] = "/mutated.dll").Compile("ok", 10000);
        Check(response.Ok && Encoding.UTF8.GetString(Convert.FromBase64String(response.AssemblyBase64!)) == "/old.dll"); child.Dead();
    }
    private static void BeforeStart()
    {
        var called = 0;
        var client = new CompilerHostClient(() => { called++; throw new Exception("must not launch"); }, () => new List<string>());
        foreach (var source in new[] { "", "\ud800", new string('a', ProtocolConstants.MaxSourceChars + 1) }) Refused(client.Compile(source, 1000), "compiler_preparation_failed");
        Check(called == 0);
        foreach (var paths in new[] { new List<string> { "\udfff" }, Enumerable.Repeat("a", 257).ToList(), new List<string> { new string('a', 32769) }, Enumerable.Repeat(new string('Ж', 32768), 6).ToList() })
        {
            var invalid = new CompilerHostClient(() => { called++; throw new Exception(); }, () => paths);
            Refused(invalid.Compile("source", 1000), "compiler_preparation_failed"); Check(called == 0);
        }
        JsonFraming.PrepareCompilerRequest(new CompilerRequest { Source = "source", ReferencePaths = Enumerable.Repeat(new string('Ж', 32768), 5).ToList() });
    }
    private static void InternalReader()
    {
        var valid = JsonSerializer.Serialize(new CompilerRequest { Source = "source" });
        foreach (var bad in new[] { "{}", "null", valid.Replace("\"protocol\":\"" + ProtocolConstants.Version + "\",", ""),
            valid.Replace("\"source\":\"source\"", "\"source\":null"), valid.Replace("\"reference_paths\":[]", "\"reference_paths\":null"),
            valid.Replace("\"reference_paths\":[]", "\"reference_paths\":[],\"extra\":1"),
            valid.Replace("\"source\":\"source\"", "\"source\":\"source\",\"source\":\"source\""),
            valid.Replace("\"source\":\"source\"", "\"source\":\"\\uD800\"") })
        {
            using var frame = Frame(bad); Exception? failure = null;
            try { JsonFraming.ReadCompilerRequest(frame); } catch (Exception error) { failure = error; }
            Check(failure != null, "accepted " + bad);
        }
        using var oversize = new MemoryStream(BitConverter.GetBytes(ProtocolConstants.MaxCompilerRequestFrameBytes + 1));
        Throws<InvalidDataException>(() => JsonFraming.ReadCompilerRequest(oversize));
    }
    private static void PreparationErrors()
    {
        using var child = new ChildFixture();
        Refused(new CompilerHostClient(child.DirectoryPath).Compile("source", 1000), "compiler_host_missing");
        Refused(child.Client("success", () => throw new IOException("references failed")).Compile("source", 1000), "compiler_preparation_failed");
        Check(!File.Exists(child.PidPath));
        var invalid = new CompilerHostClient(() => new ProcessStartInfo(Path.Combine(child.DirectoryPath, "missing")), () => new List<string>());
        Refused(invalid.Compile("source", 1000), "compiler_start_failed");
    }
    private static void Success()
    {
        using var child = new ChildFixture(); var source = "source Ж😀";
        var response = child.Client("success").Compile(source, 10000);
        Check(response.Ok && Encoding.UTF8.GetString(Convert.FromBase64String(response.AssemblyBase64!)) == Hash(source)); child.Dead();
    }
    private static void Rejected()
    { using var child = new ChildFixture(); Refused(child.Client("reject").Compile("source", 10000), "fixture_rejected"); child.Dead(); }
    private static void ActualHost()
    {
        using var child = new ChildFixture(); var result = child.Client("actual_host").Compile(new string('Ж', 4 * 1024 * 1024), 30000);
        Refused(result, "RevitAPI reference is missing"); child.Dead(); // Real host reader/compiler, not an invocation.
    }
    private static void BlockedInput()
    { using var child = new ChildFixture(); var result = child.Client("no_read").Compile(new string('Ж', 4 * 1024 * 1024), 1000); Refused(result, "compiler_timeout"); child.Dead(); }
    private static void BlockedOutput()
    { using var child = new ChildFixture(); Refused(child.Client("no_output").Compile("source", 500), "compiler_timeout"); child.Dead(); }
    private static void Cancelled()
    {
        using var child = new ChildFixture(); using var cancel = new CancellationTokenSource();
        var task = Task.Run(() => child.Client("no_output").Compile("source", 10000, cancel.Token));
        Check(SpinWait.SpinUntil(() => File.Exists(child.PidPath), 5000)); cancel.Cancel();
        var result = task.WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult(); Refused(result, "compiler_cancelled"); child.Dead();
    }
    private static void StderrFlood()
    { using var child = new ChildFixture(); Check(child.Client("stderr_success").Compile("source", 10000).Ok); child.Dead(); }
    private static void StderrFailure()
    {
        using var child = new ChildFixture(); var result = child.Client("stderr_reject").Compile("source", 10000);
        Refused(result, "fixture_rejected"); Check(result.Diagnostics.Any(value => value.Contains("truncated")) && result.Diagnostics.Sum(value => value.Length) < 67000); child.Dead();
    }
    private static void EarlyExit()
    { using var child = new ChildFixture(); Refused(child.Client("early_exit").Compile(new string('Ж', 4 * 1024 * 1024), 10000), "compiler_request_write_failed"); child.Dead(); }
    private static void Linger()
    { using var child = new ChildFixture(); Refused(child.Client("linger").Compile("source", 500), "compiler_timeout"); child.Dead(); }
    private static void BadFrames()
    {
        foreach (var mode in new[] { "malformed", "truncated", "oversize", "duplicate", "trailing", "second_frame", "invalid_utf8" })
        { using var child = new ChildFixture(); Refused(child.Client(mode).Compile("source", 10000), "compiler_response_read_failed"); child.Dead(); }
    }
    private static void Contradictions()
    {
        foreach (var mode in new[] { "positive_exit2", "negative_exit0", "positive_exit7", "empty_assembly", "invalid_base64", "negative_assembly", "null_diagnostics", "empty_rejection" })
        { using var child = new ChildFixture(); Refused(child.Client(mode).Compile("source", 10000), "compiler_exit_failed"); child.Dead(); }
    }
    private static void ChildException()
    { using var child = new ChildFixture(); Refused(child.Client("exception").Compile("source", 10000), "compiler_response_read_failed"); child.Dead(); }
    private static void RepeatedTimeout()
    { for (var i = 0; i < 5; i++) { using var child = new ChildFixture(); Refused(child.Client("no_output").Compile("source", 250), "compiler_timeout"); child.Dead(); } }

    private static int Child(string mode, string pidPath)
    {
        File.WriteAllText(pidPath, Process.GetCurrentProcess().Id.ToString());
        if (mode == "actual_host") return Kir.Revit.CompilerHost.Program.Main();
        if (mode == "no_read") { Thread.Sleep(Timeout.Infinite); return 9; }
        if (mode == "early_exit") return 7;
        var request = JsonFraming.ReadCompilerRequest(Console.OpenStandardInput());
        if (mode == "no_output") { Thread.Sleep(Timeout.Infinite); return 9; }
        if (mode == "exception") throw new InvalidOperationException("actual child fixture exception");
        if (mode.StartsWith("stderr_", StringComparison.Ordinal))
        {
            var bytes = Encoding.UTF8.GetBytes(new string('e', 8192)); var stderr = Console.OpenStandardError();
            for (var i = 0; i < 512; i++) stderr.Write(bytes); stderr.Flush();
        }
        var output = Console.OpenStandardOutput();
        if (mode == "malformed") { using var frame = Frame("not-json"); frame.CopyTo(output); return 2; }
        if (mode == "duplicate") { using var frame = Frame("{\"ok\":true,\"ok\":false}"); frame.CopyTo(output); return 2; }
        if (mode == "truncated") { output.Write(BitConverter.GetBytes(100)); output.WriteByte((byte)'{'); return 2; }
        if (mode == "oversize") { output.Write(BitConverter.GetBytes(ProtocolConstants.MaxFrameBytes + 1)); return 2; }
        if (mode == "invalid_utf8") { output.Write(BitConverter.GetBytes(1)); output.WriteByte(0xff); return 2; }
        var response = mode == "reject" || mode == "stderr_reject" || mode == "negative_exit0" || mode == "negative_assembly" || mode == "empty_rejection" ? Negative() : Positive(request.Source);
        if (mode == "empty_rejection") response.Diagnostics.Clear();
        if (mode == "empty_assembly") response.AssemblyBase64 = "";
        if (mode == "invalid_base64") response.AssemblyBase64 = "not base64";
        if (mode == "negative_assembly") response.AssemblyBase64 = "AQ==";
        if (mode == "null_diagnostics") response.Diagnostics = null!;
        if (mode == "reference_echo") response.AssemblyBase64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(request.ReferencePaths.Single()));
        JsonFraming.Write(output, response);
        if (mode == "trailing") output.WriteByte(1);
        if (mode == "second_frame") JsonFraming.Write(output, response);
        if (mode == "linger") { Thread.Sleep(Timeout.Infinite); return 9; }
        return mode == "positive_exit7" ? 7 : mode == "positive_exit2" ? 2 : mode == "negative_exit0" ? 0 : response.Ok ? 0 : 2;
    }
    private static int Profile()
    {
        using var input = JsonDocument.Parse(Console.In.ReadToEnd()); var source = input.RootElement.GetProperty("source").GetString()!;
        var prepared = JsonFraming.PrepareCompilerRequest(new CompilerRequest { Source = source });
        var recovered = Roundtrip(prepared); using var child = new ChildFixture(); var response = child.Client("success").Compile(source, 30000); child.Dead();
        Check(response.Ok && recovered.Source == source && Encoding.UTF8.GetString(Convert.FromBase64String(response.AssemblyBase64!)) == Hash(source));
        Console.WriteLine(JsonSerializer.Serialize(new { payload_bytes = prepared.PayloadLength, utf16_units = source.Length, roundtrip_exact = true, child_exited = true })); return 0;
    }
}
