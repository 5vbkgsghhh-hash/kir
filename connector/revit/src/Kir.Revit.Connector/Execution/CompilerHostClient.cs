using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class CompilerHostClient
    {
        private static readonly HashSet<string> ReferenceAllowlist = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "mscorlib", "netstandard", "System", "System.Core", "System.Private.CoreLib", "System.Runtime",
            "System.Runtime.Extensions", "System.Collections", "System.Collections.Concurrent", "System.Collections.NonGeneric",
            "System.Collections.Specialized", "System.Linq", "System.Linq.Expressions", "System.ObjectModel", "System.Memory",
            "System.Private.Uri", "System.Runtime.Numerics", "System.ComponentModel.Primitives", "System.ComponentModel.TypeConverter",
            "System.Text.RegularExpressions", "RevitAPI", "RevitAPIUI",
        };
        private const int CleanupMs = 5000;
        private readonly string? _hostPath;
        private readonly Func<ProcessStartInfo> _startInfo;
        private readonly Func<List<string>> _references;
        private readonly int _minimumTimeoutMs;

        public CompilerHostClient(string addinDirectory)
        {
            _hostPath = Path.Combine(addinDirectory, "compiler", "Kir.Revit.CompilerHost.exe");
            _startInfo = () => new ProcessStartInfo { FileName = _hostPath };
            _references = ReferencePaths;
            _minimumTimeoutMs = 1000;
        }

        // Only process launch/reference discovery are substituted by the real
        // no-Revit child fixture; framing and supervision stay production code.
        internal CompilerHostClient(Func<ProcessStartInfo> startInfo, Func<List<string>> references, int minimumTimeoutMs = 1000)
        {
            _startInfo = startInfo ?? throw new ArgumentNullException(nameof(startInfo));
            _references = references ?? throw new ArgumentNullException(nameof(references));
            if (minimumTimeoutMs < 1 || minimumTimeoutMs > 120000) throw new ArgumentOutOfRangeException(nameof(minimumTimeoutMs));
            _minimumTimeoutMs = minimumTimeoutMs;
        }

        public CompilerResponse Compile(string source, int timeoutMs) => Compile(source, timeoutMs, CancellationToken.None);

        public CompilerResponse Compile(string source, int timeoutMs, CancellationToken cancellationToken)
        {
            JsonFraming.PreparedCompilerRequest prepared;
            ProcessStartInfo startInfo;
            try
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (_hostPath != null && !File.Exists(_hostPath))
                    return Failure("compiler_host_missing", "compiler host not found: " + _hostPath);
                prepared = JsonFraming.PrepareCompilerRequest(new CompilerRequest { Source = source, ReferencePaths = _references() });
                // The complete detached frame exists before even invoking this
                // factory, and necessarily before Process.Start.
                startInfo = _startInfo();
                startInfo.UseShellExecute = false;
                startInfo.CreateNoWindow = true;
                startInfo.RedirectStandardInput = true;
                startInfo.RedirectStandardOutput = true;
                startInfo.RedirectStandardError = true;
            }
            catch (OperationCanceledException) { return Failure("compiler_cancelled", "cancelled before process start"); }
            catch (Exception error) { return Failure("compiler_preparation_failed", error.Message); }
            return Run(prepared, startInfo, Math.Max(_minimumTimeoutMs, Math.Min(timeoutMs, 120000)), cancellationToken)
                .GetAwaiter().GetResult();
        }

        private static async Task<CompilerResponse> Run(JsonFraming.PreparedCompilerRequest prepared,
            ProcessStartInfo startInfo, int timeoutMs, CancellationToken caller)
        {
            using (var process = new Process { StartInfo = startInfo })
            using (var deadline = CancellationTokenSource.CreateLinkedTokenSource(caller))
            {
                var result = Failure("compiler_internal", "compiler exchange did not complete");
                var started = false;
                var tasks = new List<Task>();
                var stderr = new StderrExcerpt();
                var phase = "start";
                deadline.CancelAfter(timeoutMs);
                try
                {
                    deadline.Token.ThrowIfCancellationRequested();
                    if (!process.Start()) throw new IOException("compiler process did not start");
                    started = true;
                    var errors = stderr.Drain(process.StandardError.BaseStream, deadline.Token);
                    tasks.Add(errors);
                    var response = ReadResponse(process.StandardOutput.BaseStream, deadline.Token);
                    tasks.Add(response);
                    var write = Send(prepared, process.StandardInput, deadline.Token);
                    tasks.Add(write);
                    var exchange = CompleteExchange(process, write, response, errors, deadline.Token, value => phase = value);
                    tasks.Add(exchange);
                    // Standard process pipes are not uniformly cancellable on
                    // every supported runtime. The supervisor deadline must be
                    // able to kill the child even if an I/O await ignores it.
                    if (await Task.WhenAny(exchange, Task.Delay(Timeout.Infinite, deadline.Token)).ConfigureAwait(false) != exchange)
                        throw new OperationCanceledException(deadline.Token);
                    result = await exchange.ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    result = Failure(caller.IsCancellationRequested ? "compiler_cancelled" : "compiler_timeout",
                        "compiler " + phase + " did not complete before cancellation/deadline");
                }
                catch (Exception error) { result = Failure("compiler_" + phase + "_failed", error.Message); }
                finally
                {
                    deadline.Cancel();
                    if (!started)
                    {
                        // Recover an associated handle if Start threw after OS
                        // creation; Dispose alone would not terminate that child.
                        try { _ = process.Id; started = true; } catch (InvalidOperationException) { }
                    }
                    if (started && !await Cleanup(process, tasks).ConfigureAwait(false))
                        result = Failure("compiler_cleanup_unconfirmed",
                            "child termination or I/O cleanup could not be confirmed; no Revit execution was dispatched");
                }
                if (!result.Ok && stderr.HasData) result.Diagnostics.Add(stderr.Describe());
                return result;
            }
        }

        private static async Task<CompilerResponse> CompleteExchange(Process process, Task write,
            Task<CompilerResponse> response, Task errors, CancellationToken token, Action<string> phase)
        {
            phase("request_write"); await write.ConfigureAwait(false);
            phase("response_read"); var result = await response.ConfigureAwait(false);
            phase("exit");
            while (!process.WaitForExit(0)) await Task.Delay(20, token).ConfigureAwait(false);
            await errors.ConfigureAwait(false);
            ValidateResponse(result, process.ExitCode);
            return result;
        }

        private static async Task Send(JsonFraming.PreparedCompilerRequest prepared, StreamWriter input, CancellationToken token)
        {
            await prepared.WriteAsync(input.BaseStream, token).ConfigureAwait(false);
            input.Close();
        }

        private static async Task<CompilerResponse> ReadResponse(Stream output, CancellationToken token)
        {
            var response = await JsonFraming.ReadAsync<CompilerResponse>(output, token).ConfigureAwait(false);
            var trailing = new byte[1];
            if (await output.ReadAsync(trailing, 0, 1, token).ConfigureAwait(false) != 0)
                throw new InvalidDataException("trailing stdout after the compiler response frame");
            return response;
        }

        private static void ValidateResponse(CompilerResponse response, int exitCode)
        {
            if (response.Diagnostics == null || response.Diagnostics.Any(value => value == null))
                throw new InvalidDataException("compiler response has invalid diagnostics");
            if ((response.Ok && exitCode != 0) || (!response.Ok && exitCode != 2))
                throw new InvalidDataException("compiler response contradicts process exit code " + exitCode);
            if (response.Ok)
            {
                if (string.IsNullOrWhiteSpace(response.AssemblyBase64) || Convert.FromBase64String(response.AssemblyBase64).Length == 0)
                    throw new InvalidDataException("successful compiler response has no nonempty Base64 assembly");
                // Base64 is only a transport check, not PE/CodePolicy verification.
            }
            else
            {
                if (response.AssemblyBase64 != null)
                    throw new InvalidDataException("refusing compiler response contains an assembly payload");
                if (!response.Diagnostics.Any(value => !string.IsNullOrWhiteSpace(value)))
                    throw new InvalidDataException("refusing compiler response has no diagnostic");
            }
        }

        private static async Task<bool> Cleanup(Process process, List<Task> tasks)
        {
            var watch = Stopwatch.StartNew();
            var confirmed = true;
            try
            {
                if (!process.HasExited) process.Kill();
                if (!process.WaitForExit(CleanupMs)) confirmed = false;
            }
            catch
            {
                try { confirmed = process.HasExited; }
                catch { confirmed = false; }
            }
            try { process.StandardInput.Close(); } catch { }
            try { process.StandardOutput.Close(); } catch { }
            try { process.StandardError.Close(); } catch { }
            var pending = Task.WhenAll(tasks);
            var remaining = Math.Max(1, CleanupMs - (int)watch.ElapsedMilliseconds);
            if (await Task.WhenAny(pending, Task.Delay(remaining)).ConfigureAwait(false) != pending) confirmed = false;
            // Observe late faults even when the OS could not confirm cleanup.
            _ = pending.ContinueWith(task => { _ = task.Exception; }, CancellationToken.None,
                TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
            return confirmed;
        }

        private sealed class StderrExcerpt
        {
            private const int RetainedBytes = 65536;
            private readonly MemoryStream _prefix = new MemoryStream();
            private readonly object _gate = new object();
            private long _total;
            public bool HasData { get { lock (_gate) return _total > 0; } }
            public async Task Drain(Stream stream, CancellationToken token)
            {
                var buffer = new byte[4096];
                int read;
                while ((read = await stream.ReadAsync(buffer, 0, buffer.Length, token).ConfigureAwait(false)) > 0)
                {
                    lock (_gate)
                    {
                        var retained = Math.Min(read, RetainedBytes - (int)_prefix.Length);
                        if (retained > 0) _prefix.Write(buffer, 0, retained);
                        _total += read;
                    }
                    // Keep draining after the retained prefix fills: stopping
                    // here would let a verbose child block on its stderr pipe.
                }
            }
            public string Describe()
            {
                lock (_gate) return "compiler_stderr_excerpt" + (_total > _prefix.Length ? " (truncated)" : "") +
                    ": " + Encoding.UTF8.GetString(_prefix.ToArray());
            }
        }

        private static List<string> ReferencePaths()
        {
            return AppDomain.CurrentDomain.GetAssemblies()
                .Where(a => !a.IsDynamic && ReferenceAllowlist.Contains(a.GetName().Name ?? string.Empty))
                .Select(a => a.Location).Where(path => !string.IsNullOrWhiteSpace(path) && File.Exists(path))
                .Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        private static CompilerResponse Failure(string code, string message) =>
            new CompilerResponse { Ok = false, Diagnostics = { code + ": " + message } };
    }
}
