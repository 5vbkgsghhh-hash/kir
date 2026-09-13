using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Transport
{
    internal sealed class DiscoveryFile : IDisposable
    {
        private readonly byte[] _published;
        public string Path { get; }

        public DiscoveryFile(string root, DiscoveryRecord record) : this(root, record, PrepareDirectory) { }

        internal DiscoveryFile(string root, DiscoveryRecord record, Action<string> prepareDirectory)
        {
            Validate(record);
            var directory = System.IO.Path.Combine(root, "discovery", record.Target!.InstanceId);
            prepareDirectory(directory);
            Path = System.IO.Path.Combine(directory, record.SessionId + ".json");
            _published = JsonSerializer.SerializeToUtf8Bytes(record);
            var temporary = Path + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write,
                    FileShare.None, 4096, FileOptions.WriteThrough))
                { stream.Write(_published, 0, _published.Length); stream.Flush(true); }
                // Publish one complete file, without replacing any existing session.
                File.Move(temporary, Path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        internal static void Validate(DiscoveryRecord record)
        {
            if (record == null || record.Target == null) throw new ArgumentException("discovery target is required");
            if (record.Protocol != ProtocolConstants.Version) throw new ArgumentException("discovery protocol mismatch");
            if (record.SessionId != ConnectorTarget.CanonicalUuid(record.SessionId, "session_id"))
                throw new ArgumentException("discovery session_id must be canonical");
            if (string.IsNullOrWhiteSpace(record.PipeName) || string.IsNullOrWhiteSpace(record.Token) || record.ProcessId <= 0)
                throw new ArgumentException("discovery pipe, token and process id are required");
            if (!DateTime.TryParseExact(record.ExpiresUtc, "O", CultureInfo.InvariantCulture,
                DateTimeStyles.RoundtripKind, out var expires) || expires.Kind != DateTimeKind.Utc || expires <= DateTime.UtcNow)
                throw new ArgumentException("discovery expiry must be a future UTC instant");
        }

        // Only the new v4 root/owned descendants, never legacy global files.
        // Windows inheritance protects both journals and discovery children.
        internal static void PrepareDirectory(string directory)
        {
            using (var identity = WindowsIdentity.GetCurrent())
            {
                var sid = identity.User ?? throw new InvalidOperationException("current Windows SID is unavailable");
                Directory.CreateDirectory(directory);
                var security = new DirectorySecurity();
                security.SetAccessRuleProtection(true, false);
                security.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                    PropagationFlags.None, AccessControlType.Allow));
                new DirectoryInfo(directory).SetAccessControl(security);
            }
        }

        public void Dispose()
        {
            // Session-qualified names prevent old-instance cleanup from deleting
            // new discovery. The byte check also preserves a replaced file, but
            // is not a sandbox against hostile same-account filesystem races.
            try { if (File.Exists(Path) && File.ReadAllBytes(Path).SequenceEqual(_published)) File.Delete(Path); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
