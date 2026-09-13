using System;
using System.Globalization;
using System.Threading;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Connector.Transport;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector
{
    internal sealed class ConnectorSession : IDisposable
    {
        private readonly SessionAdmission _admission;
        private readonly IConnectorListener _pipe;
        private readonly IDisposable _discovery;
        private readonly IDisposable _expiry;
        private int _disposed;
        public string SessionId => _admission.SessionId;
        public bool IsOpen => Volatile.Read(ref _disposed) == 0 && _admission.IsOpen;

        public ConnectorSession(string root, DiscoveryRecord record, ConnectorService service, Action<string> expire)
            : this(record, service, expire, new NamedPipeHost(record.PipeName, service.Handle),
                () => new DiscoveryFile(root, record),
                (due, callback) => new Timer(_ => callback(), null, due, Timeout.InfiniteTimeSpan)) { }

        // Only resource creation is injected: lifecycle/admission/publication
        // ordering is the production algorithm, including in portable tests.
        internal ConnectorSession(DiscoveryRecord record, ConnectorService service, Action<string> expire,
            IConnectorListener pipe, Func<IDisposable> publish, Func<TimeSpan, Action, IDisposable> timer)
        {
            _admission = service.Admission;
            _pipe = pipe;
            IDisposable? discovery = null;
            IDisposable? expiry = null;
            try
            {
                DiscoveryFile.Validate(record);
                if (!service.HasToken(record.Token) || !service.Target.Matches(record.Target) || record.SessionId != _admission.SessionId ||
                    record.ExpiresUtc != _admission.ExpiresUtc.ToString("O", CultureInfo.InvariantCulture))
                    throw new ArgumentException("discovery does not describe the owned service session");
                _pipe.Start();
                discovery = publish();
                var due = _admission.ExpiresUtc - DateTime.UtcNow;
                if (due < TimeSpan.Zero) due = TimeSpan.Zero;
                expiry = timer(due, () => { _admission.Close(); expire(SessionId); });
                _discovery = discovery;
                _expiry = expiry;
            }
            catch
            {
                _admission.Close();
                expiry?.Dispose();
                _pipe.Dispose();
                discovery?.Dispose();
                throw;
            }
        }

        public void CloseAdmission() => _admission.Close();

        public void Dispose()
        {
            _admission.Close();
            if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
            _expiry.Dispose();
            try { _pipe.Dispose(); }
            finally { _discovery.Dispose(); }
        }
    }
}
