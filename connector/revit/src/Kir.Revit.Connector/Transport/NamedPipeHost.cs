using System;
using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;
using System.Threading.Tasks;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Transport
{
    internal interface IConnectorListener : IDisposable { void Start(); }

    internal sealed class NamedPipeHost : IConnectorListener
    {
        private readonly object _gate = new object();
        private readonly string _pipeName;
        private readonly Func<ConnectorRequest, Task<ConnectorResponse>> _handler;
        private readonly CancellationTokenSource _stop = new CancellationTokenSource();
        private readonly CancellationToken _stopping;
        private readonly TimeSpan _ioTimeout;
        private NamedPipeServerStream? _active;
        private Task? _loop;
        private bool _disposed;

        public NamedPipeHost(string pipeName, Func<ConnectorRequest, Task<ConnectorResponse>> handler)
            : this(pipeName, handler, TimeSpan.FromSeconds(30)) { }

        internal NamedPipeHost(string pipeName, Func<ConnectorRequest, Task<ConnectorResponse>> handler, TimeSpan ioTimeout)
        {
            if (ioTimeout <= TimeSpan.Zero || ioTimeout.TotalMilliseconds > int.MaxValue)
                throw new ArgumentOutOfRangeException(nameof(ioTimeout));
            _pipeName = pipeName;
            _handler = handler;
            _stopping = _stop.Token;
            _ioTimeout = ioTimeout;
        }

        public void Start()
        {
            lock (_gate)
            {
                if (_disposed) throw new ObjectDisposedException(nameof(NamedPipeHost));
                if (_loop != null) throw new InvalidOperationException("pipe already started");
                var first = CreatePipe(); // Bind synchronously BEFORE publishing discovery.
                _active = first;
                _loop = Task.Run(() => Run(first));
            }
        }

        internal Task Completion { get { lock (_gate) return _loop ?? Task.CompletedTask; } }

        private async Task Run(NamedPipeServerStream pipe)
        {
            using (pipe)
            {
                while (!_stopping.IsCancellationRequested)
                {
                    var connected = false;
                    var responseStarted = false;
                    try
                    {
                        await pipe.WaitForConnectionAsync(_stopping).ConfigureAwait(false);
                        connected = true;
                        var request = await Io(token => JsonFraming.ReadAsync<ConnectorRequest>(pipe, token), "frame_read").ConfigureAwait(false);
                        if (_stopping.IsCancellationRequested) return;
                        // No idle I/O timer runs while an admitted operation is
                        // being awaited. An I/O timeout is never its rollback.
                        var response = await _handler(request).ConfigureAwait(false);
                        responseStarted = true;
                        await WriteResponse(pipe, response).ConfigureAwait(false);
                        await ClientEof(pipe).ConfigureAwait(false);
                    }
                    catch (OperationCanceledException) { return; }
                    catch (Exception ex)
                    {
                        if (_stopping.IsCancellationRequested) return;
                        if (!responseStarted)
                        {
                            try
                            {
                                await WriteResponse(pipe, ConnectorResponse.Failure(string.Empty,
                                    ex is IoTimeoutException ? "transport_io_timeout" : "transport_error", ex.Message)).ConfigureAwait(false);
                                await ClientEof(pipe).ConfigureAwait(false);
                            }
                            catch { }
                        }
                    }
                    lock (_gate)
                    {
                        if (_disposed) return;
                        // Keep the original bound endpoint across requests;
                        // close/recreate leaves a reconnect race on portable pipes.
                        // IsConnected can already be false after a peer EOF,
                        // while the server still needs Disconnect before reuse.
                        if (connected) pipe.Disconnect();
                    }
                }
            }
        }

        private Task<bool> WriteResponse(NamedPipeServerStream pipe, ConnectorResponse response) => Io(async token =>
        {
            await JsonFraming.WriteAsync(pipe, response, token).ConfigureAwait(false);
            return true;
        }, "frame_write");

        private async Task ClientEof(NamedPipeServerStream pipe)
        {
            var trailing = new byte[1];
            if (await Io(token => pipe.ReadAsync(trailing, 0, 1, token), "client_eof").ConfigureAwait(false) != 0)
                throw new InvalidDataException("one request/response per connection; close after reading the framed response");
        }

        private async Task<T> Io<T>(Func<CancellationToken, Task<T>> action, string phase)
        {
            using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(_stopping))
            {
                timeout.CancelAfter(_ioTimeout);
                try { return await action(timeout.Token).ConfigureAwait(false); }
                catch (OperationCanceledException) when (!_stopping.IsCancellationRequested)
                { throw new IoTimeoutException(phase); }
            }
        }

        private sealed class IoTimeoutException : IOException
        {
            public IoTimeoutException(string phase) : base("connection I/O timed out during " + phase +
                "; no execution rollback is implied; resolve the original journal before any retry") { }
        }

        private NamedPipeServerStream CreatePipe()
        {
#if REVIT_MODERN
            return new NamedPipeServerStream(_pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly, ProtocolConstants.MaxFrameBytes,
                ProtocolConstants.MaxFrameBytes);
#else
            using (var identity = WindowsIdentity.GetCurrent())
            {
                var sid = identity.User ?? throw new InvalidOperationException("current Windows SID is unavailable");
                var security = new PipeSecurity();
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new PipeAccessRule(sid, PipeAccessRights.FullControl, AccessControlType.Allow));
                return new NamedPipeServerStream(_pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous, ProtocolConstants.MaxFrameBytes, ProtocolConstants.MaxFrameBytes, security);
            }
#endif
        }

        public void Dispose()
        {
            lock (_gate)
            {
                if (_disposed) return;
                _disposed = true;
                _stop.Cancel();
                _active?.Dispose(); // All frame and EOF I/O also receives _stopping.
                _active = null;
                _stop.Dispose();
            }
            // No API-thread wait on a handler queued to that same API thread.
            // SessionAdmission closes before this transport is disposed.
        }
    }
}
