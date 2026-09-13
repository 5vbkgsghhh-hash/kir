using System;
using System.Threading.Tasks;
using Autodesk.Revit.UI;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Context
{
    internal sealed class ContextQueryScheduler : IExternalEventHandler, IDisposable
    {
        private readonly ContextSnapshotCollector _collector;
        private readonly object _gate = new object();
        private TaskCompletionSource<ContextSnapshot>? _pending;
        private readonly ExternalEvent _event;
        private bool _disposed;

        public ContextQueryScheduler(ContextSnapshotCollector collector)
        {
            _collector = collector;
            _event = ExternalEvent.Create(this);
        }

        public Task<ContextSnapshot> Capture()
        {
            lock (_gate)
            {
                if (_disposed) return Task.FromException<ContextSnapshot>(new ObjectDisposedException(nameof(ContextQueryScheduler)));
                if (_pending != null) return _pending.Task;
                _pending = new TaskCompletionSource<ContextSnapshot>(TaskCreationOptions.RunContinuationsAsynchronously);
                var request = _event.Raise();
                if (request != ExternalEventRequest.Accepted && request != ExternalEventRequest.Pending)
                {
                    _pending.TrySetException(new InvalidOperationException("Revit rejected the context request"));
                    _pending = null;
                }
                return _pending?.Task ?? Task.FromException<ContextSnapshot>(new InvalidOperationException("context request failed"));
            }
        }

        public void Execute(UIApplication application)
        {
            TaskCompletionSource<ContextSnapshot>? completion;
            lock (_gate)
            {
                completion = _pending; _pending = null;
                if (_disposed || completion == null) return;
                try { completion.TrySetResult(_collector.Capture(application)); }
                catch (Exception ex) { completion.TrySetException(ex); }
            }
        }

        public string GetName() => "KIR local connector context";
        public void Dispose()
        {
            lock (_gate)
            {
                if (_disposed) return;
                _disposed = true;
                _pending?.TrySetCanceled();
                _pending = null;
                _event.Dispose();
            }
        }
    }
}
