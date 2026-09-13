using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Kir.Revit.Protocol;
using Microsoft.Win32.SafeHandles;

namespace Kir.Revit.PipeClient
{
    internal static class Program
    {
        public static async Task<int> Main(string[] args)
        {
            var phase = "arguments";
            var sent = false;
            try
            {
                var options = Options.Parse(args);
                if (!OperatingSystem.IsWindows()) throw new ClientFailure("unsupported_platform");
                using var deadline = new CancellationTokenSource(options.TimeoutMs);
                phase = "stdin";
                var request = await Exchange.ReadInput(Console.OpenStandardInput(), deadline.Token).ConfigureAwait(false);
                var response = await Exchange.Run(request, options.PipeName, options.ExpectedPid, deadline.Token,
                    NativeIdentity.ServerPid, (current, mayBeSent) => { phase = current; sent |= mayBeSent; }).ConfigureAwait(false);
                // Exchange has disposed the pipe before stdout is written. The
                // server must not wait for our EOF while we wait for its EOF.
                phase = "stdout";
                await Console.OpenStandardOutput().WriteAsync(response, 0, response.Length, deadline.Token).ConfigureAwait(false);
                return 0;
            }
            catch (Exception error)
            {
                var code = error is ClientFailure named ? named.Code : error is OperationCanceledException ? "deadline_exceeded" : "exchange_failed";
                Console.Error.WriteLine(JsonSerializer.Serialize(new
                {
                    schema = "kir-pipe-client-diagnostic/1", code, phase,
                    request_may_have_been_sent = sent, retry_permitted = false,
                }));
                return 2;
            }
        }
    }

    internal sealed class ClientFailure : Exception
    {
        public string Code { get; }
        public ClientFailure(string code) : base(code) { Code = code; }
    }

    internal sealed class Options
    {
        public string PipeName { get; }
        public int ExpectedPid { get; }
        public int TimeoutMs { get; }
        private Options(string pipeName, int expectedPid, int timeoutMs)
        { PipeName = pipeName; ExpectedPid = expectedPid; TimeoutMs = timeoutMs; }
        public static Options Parse(string[] args)
        {
            if (args.Length != 7 || args[0] != "exchange") throw new ClientFailure("invalid_arguments");
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var i = 1; i < args.Length; i += 2)
                if (!values.TryAdd(args[i], args[i + 1])) throw new ClientFailure("invalid_arguments");
            if (!values.TryGetValue("--pipe", out var pipe) || !Regex.IsMatch(pipe, "\\A[A-Za-z0-9_.-]{1,256}\\z")
                || !values.TryGetValue("--expected-server-pid", out var pidText) || !int.TryParse(pidText, out var pid) || pid <= 0
                || !values.TryGetValue("--timeout-ms", out var timeoutText) || !int.TryParse(timeoutText, out var timeout) || timeout < 1000 || timeout > 300000)
                throw new ClientFailure("invalid_arguments");
            return new Options(pipe, pid, timeout);
        }
    }

    internal static class Exchange
    {
        internal static async Task<byte[]> ReadInput(Stream input, CancellationToken token)
        {
            using var retained = new MemoryStream();
            var buffer = new byte[65536];
            int read;
            while ((read = await input.ReadAsync(buffer, 0, buffer.Length, token).ConfigureAwait(false)) > 0)
            {
                if (retained.Length + read > ProtocolConstants.MaxFrameBytes) throw new ClientFailure("request_budget_exceeded");
                retained.Write(buffer, 0, read);
            }
            var bytes = retained.ToArray(); ValidateRequest(bytes); return bytes;
        }

        private static void ValidateRequest(byte[] bytes)
        {
            if (bytes.Length == 0 || bytes.Length > ProtocolConstants.MaxFrameBytes) throw new ClientFailure("request_budget_exceeded");
            using (var parsed = StrictJson.Parse(bytes))
            {
                RequestKinds.ValidateCancellationPayload(parsed.RootElement);
                var request = JsonSerializer.Deserialize<ConnectorRequest>(bytes, JsonFraming.Options);
                if (request == null || request.Protocol != ProtocolConstants.Version || string.IsNullOrWhiteSpace(request.RequestId)
                    || request.Target == null || string.IsNullOrWhiteSpace(request.Token)
                    || !RequestKinds.IsKnown(request.Kind))
                    throw new ClientFailure("invalid_request");
                ConnectorTarget.CanonicalUuid(request.SessionId, "session_id");
            }
        }

        // Portable tests inject the PID probe, not a production flag that can
        // bypass Windows identity checks. All pipe/framing code remains real.
        internal static async Task<byte[]> Run(byte[] request, string pipeName, int expectedPid, CancellationToken token,
            Func<SafePipeHandle, uint> probe, Action<string, bool> progress)
        {
            var detached = (byte[])request.Clone();
            progress("request_validation", false); ValidateRequest(detached);
            using var pipe = new NamedPipeClientStream(".", pipeName, PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly, TokenImpersonationLevel.Anonymous);
            progress("connect", false);
            await pipe.ConnectAsync(token).ConfigureAwait(false);
            progress("server_identity", false);
            uint actual;
            try { actual = probe(pipe.SafePipeHandle); }
            catch { throw new ClientFailure("server_identity_unavailable"); }
            if (actual != expectedPid) throw new ClientFailure("server_pid_mismatch");
            progress("request_write", true);
            await JsonFraming.WriteRawAsync(pipe, detached, token).ConfigureAwait(false);
            progress("response_read", true);
            return await JsonFraming.ReadRawAsync(pipe, token).ConfigureAwait(false);
        }
    }

    internal static class NativeIdentity
    {
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
        public static uint ServerPid(SafePipeHandle pipe)
        {
            if (!OperatingSystem.IsWindows() || !GetNamedPipeServerProcessId(pipe, out var pid) || pid == 0)
                throw new ClientFailure("server_identity_unavailable");
            return pid;
        }
    }
}
