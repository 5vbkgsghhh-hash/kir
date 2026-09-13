using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;
using Autodesk.Revit.UI;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class ExternalEventScheduler : IExternalEventHandler, IDisposable
    {
        private readonly ConcurrentQueue<ExecutionWorkItem> _queue = new ConcurrentQueue<ExecutionWorkItem>();
        private readonly ExecutionEngine _engine;
        private readonly ExternalEvent _externalEvent;
        private readonly object _gate = new object();
        private bool _disposed;
        private bool _executing;

        public ExternalEventScheduler(ExecutionEngine engine)
        {
            _engine = engine;
            _externalEvent = ExternalEvent.Create(this);
        }

        public Task<OperationReceipt> Enqueue(ExecutionWorkItem item)
        {
            lock (_gate)
            {
                if (_disposed)
                    item.Completion.TrySetResult(_engine.RuntimeClosed(item));
                else { _queue.Enqueue(item); RaiseOrReject(); }
                return item.Completion.Task;
            }
        }

        public void Execute(UIApplication application)
        {
            // Shutdown cannot release the journal owner while an invocation is
            // inside this gate. Session Close uses its own short admission gate.
            lock (_gate)
            {
                if (_disposed) return;
                if (_queue.TryDequeue(out var item))
                {
                    _executing = true;
                    try { item.Completion.TrySetResult(_engine.Execute(application, item)); }
                    catch (Exception ex) { item.Completion.TrySetResult(_engine.FailedUnknown(item, ex)); }
                    finally { _executing = false; }
                }
                if (!_queue.IsEmpty) RaiseOrReject();
            }
        }

        private void RaiseOrReject()
        {
            try
            {
                var request = _externalEvent.Raise();
                if (request == ExternalEventRequest.Accepted || request == ExternalEventRequest.Pending) return;
            }
            catch { /* No accepted wake-up: settle every queued item explicitly. */ }
            while (_queue.TryDequeue(out var item))
                item.Completion.TrySetResult(_engine.Rejected(item, "Revit rejected the ExternalEvent request"));
        }

        public string GetName() => "KIR local connector execution";
        public void Dispose()
        {
            lock (_gate)
            {
                if (_disposed) return;
                if (_executing) throw new InvalidOperationException("cannot release runtime ownership from a reentrant in-flight invocation");
                _disposed = true;
                while (_queue.TryDequeue(out var item))
                    item.Completion.TrySetResult(_engine.Cancelled(item, "runtime shut down before execution admission"));
                _externalEvent.Dispose();
            }
        }
    }
}
