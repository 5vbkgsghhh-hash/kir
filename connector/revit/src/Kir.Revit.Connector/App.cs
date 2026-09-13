using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using Autodesk.Revit.UI;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Connector.Transport;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector
{
    public sealed class App : IExternalApplication
    {
        internal static App? Instance { get; private set; }
        private readonly object _sessionGate = new object();
        private readonly string _root;
        private readonly Action<string> _prepareDirectory;
        private readonly Func<string, DiscoveryRecord, ConnectorService, Action<string>, ConnectorSession> _createSession;
        private DocumentRevisionTracker? _revisions;
        private ContextQueryScheduler? _contextQueries;
        private ExternalEventScheduler? _execution;
        private JournalOwner? _owner;
        private ConnectorSession? _session;
        private bool _stopping;

        public App() : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "KIR", "connector", "v4"), DiscoveryFile.PrepareDirectory,
            (root, record, service, expire) => new ConnectorSession(root, record, service, expire)) { }

        internal App(string root, Action<string> prepareDirectory,
            Func<string, DiscoveryRecord, ConnectorService, Action<string>, ConnectorSession> createSession)
        {
            _root = root;
            _prepareDirectory = prepareDirectory;
            _createSession = createSession;
        }

        public Result OnStartup(UIControlledApplication application)
        {
            if (_owner != null || _stopping) return Result.Failed;
            try
            {
                // The native application supplies the year; a client-selected
                // compilation year cannot establish the identity of this host.
                var target = new ConnectorTarget(Guid.NewGuid().ToString("D"), Guid.NewGuid().ToString("D"),
                    application.ControlledApplication.VersionNumber);
                _prepareDirectory(_root);
                _owner = JournalOwner.CreateNew(_root, target);
                _revisions = new DocumentRevisionTracker(application.ControlledApplication);
                var collector = new ContextSnapshotCollector(_revisions);
                _contextQueries = new ContextQueryScheduler(collector);
                _execution = new ExternalEventScheduler(new ExecutionEngine(collector, _owner.Journal));
                const string tab = "KIR";
                try { application.CreateRibbonTab(tab); } catch { }
                var panel = application.CreateRibbonPanel(tab, "Connector");
                panel.AddItem(new PushButtonData("KirConnectorToggle", "Local\nConnector",
                    Assembly.GetExecutingAssembly().Location, "Kir.Revit.Connector.Commands.ToggleConnectorCommand")
                {
                    ToolTip = "Enable this Revit process's current-user-only KIR connector for ten minutes.",
                    LongDescription = "Generated code can modify the active Revit document. Enable only while using a trusted local KIR client.",
                });
                Instance = this;
                return Result.Succeeded;
            }
            catch
            {
                _execution?.Dispose();
                _contextQueries?.Dispose();
                _revisions?.Dispose();
                _owner?.Dispose();
                _owner = null;
                _stopping = true;
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            lock (_sessionGate) _stopping = true;
            Disable();
            try { _execution?.Dispose(); }
            catch (InvalidOperationException)
            {
                // Reentrant shutdown from inside an admitted invocation cannot
                // release its owner lease. No rollback or cancellation is claimed.
                // A later normal shutdown (or process death) releases ownership.
                return Result.Failed;
            }
            _contextQueries?.Dispose();
            _revisions?.Dispose();
            _owner?.Dispose();
            _owner = null;
            if (ReferenceEquals(Instance, this)) Instance = null;
            return Result.Succeeded;
        }

        internal ConnectorTarget? Target => _owner?.Target;
        internal bool IsEnabled { get { lock (_sessionGate) return _session?.IsOpen == true; } }

        internal string Enable()
        {
            lock (_sessionGate)
            {
                if (_stopping || _contextQueries == null || _execution == null || _owner == null)
                    throw new InvalidOperationException("connector is not initialized or is stopping");
                Disable();
                var admission = new SessionAdmission(Guid.NewGuid().ToString("D"), DateTime.UtcNow.AddMinutes(10));
                var token = RandomHex(32);
                var addinDirectory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)
                                     ?? throw new InvalidOperationException("add-in directory is unavailable");
                var service = new ConnectorService(token, admission, _contextQueries, _execution,
                    new CompilerHostClient(addinDirectory), _owner.Journal, _owner.Target, _root);
                var record = new DiscoveryRecord
                {
                    Target = _owner.Target,
                    SessionId = admission.SessionId,
                    PipeName = "kir-revit-" + Process.GetCurrentProcess().Id + "-" + RandomHex(12),
                    Token = token,
                    ProcessId = Process.GetCurrentProcess().Id,
                    ExpiresUtc = admission.ExpiresUtc.ToString("O", CultureInfo.InvariantCulture),
                };
                var session = _createSession(_root, record, service, DisableSession);
                if (!session.IsOpen)
                {
                    session.Dispose();
                    throw new InvalidOperationException("connector session expired before publication completed");
                }
                _session = session;
                return admission.ExpiresUtc.ToLocalTime().ToString("T");
            }
        }

        internal void Disable() => DisableSession(null);

        private void DisableSession(string? expectedSession)
        {
            ConnectorSession? session;
            lock (_sessionGate)
            {
                session = _session;
                if (session == null || (expectedSession != null && session.SessionId != expectedSession)) return;
                session.CloseAdmission();
                _session = null;
            }
            session.Dispose();
        }

        private static string RandomHex(int bytes)
        {
            var data = new byte[bytes];
            using (var random = RandomNumberGenerator.Create()) random.GetBytes(data);
            return BitConverter.ToString(data).Replace("-", string.Empty).ToLowerInvariant();
        }
    }
}
