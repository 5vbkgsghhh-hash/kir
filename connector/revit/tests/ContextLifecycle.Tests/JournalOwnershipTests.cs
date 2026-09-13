using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;

internal static class JournalOwnershipTests
{
    public static readonly (string Name, Action Run)[] Cases =
    {
        ("target canonicalizes UUIDs and validates the shipped years", Targets),
        ("recovery never creates a missing original journal", MissingRecovery),
        ("incomplete initialization is retained and refused without repair", IncompleteInitialization),
        ("existing empty or foreign journal directories are not adopted", ForeignDirectory),
        ("disposed writer cannot append after relinquishing its lease", DisposedWriter),
        ("original metadata target must match before recovery", TargetMismatch),
        ("foreign valid journal records cannot acquire the container target", ForeignRecords),
        ("corrupt owner metadata is not a not-found operation", CorruptMetadata),
        ("recovery reuses strict journal framing and detached records", RecoveryRecords),
        ("read-only recovery owns the lease until disposed", RecoveryExclusive),
        ("two independent processes can own different journals", DistinctProcesses),
        ("simultaneous creators of one identity have exactly one owner", CompetingCreators),
        ("process death releases lease without discarding durable start", CrashRecovery),
        ("new ownership does not adopt or rewrite legacy global files", LegacyGlobals),
    };

    private const string OperationId = "39bafed5-14e2-41dd-917e-33ce8611dcac";
    private static ConnectorTarget Target(string? journal = null, string? instance = null, string year = "2023") =>
        new ConnectorTarget(journal ?? Guid.NewGuid().ToString("D"), instance ?? Guid.NewGuid().ToString("D"), year);
    private static OperationInputBinding Input(ConnectorTarget target) => new OperationInputBinding(OperationId, new string('a', 64), "doc-token", 0, null, null, target);
    private static void Check(bool value, string message = "assertion failed") { if (!value) throw new Exception(message); }
    private static T Throws<T>(Action action) where T : Exception
    { try { action(); } catch (T error) { return error; } throw new Exception("expected " + typeof(T).Name); }

    private sealed class Temp : IDisposable
    {
        public string Root { get; } = Path.Combine(Path.GetTempPath(), "kir-journal-owner-" + Guid.NewGuid().ToString("N"));
        public string DirectoryOf(ConnectorTarget target) => Path.Combine(Root, "journals", target.JournalId);
        public string Journal(ConnectorTarget target) => Path.Combine(DirectoryOf(target), "operations.jsonl");
        public string Metadata(ConnectorTarget target) => Path.Combine(DirectoryOf(target), "owner.json");
        public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }
    }

    private static void Targets()
    {
        var journal = Guid.NewGuid(); var instance = Guid.NewGuid();
        var target = Target(journal.ToString("B").ToUpperInvariant(), instance.ToString("N"));
        Check(target.JournalId == journal.ToString("D") && target.InstanceId == instance.ToString("D"));
        foreach (var year in Enumerable.Range(2021, 6)) Check(Target(year: year.ToString()).RevitVersion == year.ToString());
        foreach (var id in new[] { "../foreign", "", new string('0', 32), "C:\\foreign" })
            Throws<ArgumentException>(() => Target(journal: id));
        foreach (var year in new[] { "2020", "2027", "2023.0", " 2023" }) Throws<ArgumentException>(() => Target(year: year));
        Check(target.Matches(JsonSerializer.Deserialize<ConnectorTarget>(JsonSerializer.Serialize(target))));
    }

    private static void MissingRecovery()
    {
        using var temp = new Temp();
        var error = Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, Target()));
        Check(error.Status == "journal_unavailable" && !Directory.Exists(temp.Root));
    }

    private static void ForeignDirectory()
    {
        using var temp = new Temp(); var target = Target(); var directory = temp.DirectoryOf(target);
        Directory.CreateDirectory(directory);
        Check(Throws<JournalOwnershipException>(() => JournalOwner.CreateNew(temp.Root, target)).Status == "journal_exists");
        Check(!Directory.EnumerateFileSystemEntries(directory).Any());
        File.WriteAllText(Path.Combine(directory, "operations.jsonl"), "foreign bytes");
        Throws<JournalOwnershipException>(() => JournalOwner.CreateNew(temp.Root, target));
        Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, target));
        Check(File.ReadAllText(temp.Journal(target)) == "foreign bytes" && Directory.GetFiles(directory).Length == 1);
    }

    private static void IncompleteInitialization()
    {
        using var temp = new Temp();
        foreach (var missing in new[] { "owner.lock", "owner.json", "operations.jsonl" })
        {
            var target = Target(); using (JournalOwner.CreateNew(temp.Root, target)) { }
            var path = Path.Combine(temp.DirectoryOf(target), missing);
            File.Delete(path); // Fixture's own temporary artifact only.
            var originals = Directory.GetFiles(temp.DirectoryOf(target)).ToDictionary(p => p, File.ReadAllBytes);
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, target)).Status == "journal_unavailable");
            Check(Throws<JournalOwnershipException>(() => JournalOwner.CreateNew(temp.Root, target)).Status == "journal_exists");
            Check(!File.Exists(path));
            foreach (var entry in originals) Check(File.ReadAllBytes(entry.Key).SequenceEqual(entry.Value));
        }
    }

    private static void DisposedWriter()
    {
        using var temp = new Temp(); var target = Target(); var owner = JournalOwner.CreateNew(temp.Root, target);
        owner.Dispose(); owner.Dispose();
        Throws<ObjectDisposedException>(() => owner.Journal.TryStart(Input(owner.Target), out _));
        Check(!owner.Journal.IsHealthy && File.ReadAllBytes(temp.Journal(target)).Length == 0);
        using var recovered = JournalOwner.OpenRecovery(temp.Root, target);
        Check(recovered.Get(OperationId) == null);
    }

    private static void TargetMismatch()
    {
        using var temp = new Temp(); var target = Target();
        using (JournalOwner.CreateNew(temp.Root, target)) { }
        var original = File.ReadAllBytes(temp.Metadata(target));
        foreach (var wrong in new[] { Target(target.JournalId), Target(target.JournalId, target.InstanceId, "2026") })
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, wrong)).Status == "journal_target_mismatch");
        Check(File.ReadAllBytes(temp.Metadata(target)).SequenceEqual(original));
        using var good = JournalOwner.OpenRecovery(temp.Root, target); Check(good.Target.Matches(target));
    }

    private static void ForeignRecords()
    {
        using var temp = new Temp(); var a = Target(); var b = Target(year: "2026");
        using (var owner = JournalOwner.CreateNew(temp.Root, a)) Check(owner.Journal.TryStart(Input(owner.Target), out _));
        using (var owner = JournalOwner.CreateNew(temp.Root, b)) Check(owner.Journal.TryStart(Input(owner.Target), out _));
        var originalOwner = File.ReadAllBytes(temp.Metadata(a));
        File.Copy(temp.Journal(b), temp.Journal(a), true); // Valid B bytes, unchanged A ownership metadata.
        var foreign = File.ReadAllBytes(temp.Journal(a));
        var error = Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, a));
        Check(error.Status == "journal_target_mismatch");
        Check(File.ReadAllBytes(temp.Journal(a)).SequenceEqual(foreign));
        Check(File.ReadAllBytes(temp.Metadata(a)).SequenceEqual(originalOwner));
    }

    private static void CorruptMetadata()
    {
        using var temp = new Temp(); var target = Target();
        using (JournalOwner.CreateNew(temp.Root, target)) { }
        var original = File.ReadAllText(temp.Metadata(target));
        foreach (var corrupt in new[] {
            original.Replace("\"schema_version\":1", "\"schema_version\":9"),
            original.Replace("\"schema_version\":1", "\"schema_version\":1,\"schema_version\":1"),
            original.Replace("\"schema_version\":1", "\"schema_version\":1,\"extra\":true"),
            original.Replace(target.InstanceId, "../not-an-instance"), "{}", "null", "", new string('x', 16385),
            original.Replace("\"revit_version\":\"2023\"", "\"revit_version\":\"2023\",\"other\":1") })
        {
            File.WriteAllText(temp.Metadata(target), corrupt);
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, target)).Status == "journal_unavailable");
            Check(File.ReadAllText(temp.Metadata(target)) == corrupt);
        }
        File.WriteAllText(temp.Metadata(target), original);
        using var recovered = JournalOwner.OpenRecovery(temp.Root, target);
    }

    private static void RecoveryRecords()
    {
        using var temp = new Temp(); var target = Target();
        using (var owner = JournalOwner.CreateNew(temp.Root, target)) Check(owner.Journal.TryStart(Input(owner.Target), out _));
        var bytes = File.ReadAllBytes(temp.Journal(target));
        using (var recovered = JournalOwner.OpenRecovery(temp.Root, target))
        {
            var record = recovered.Get(OperationId)!;
            Check(record.IsBound && record.Receipt == null);
            record.SourceSha256 = new string('0', 64);
            Check(recovered.Get(OperationId)!.SourceSha256 == Input(target).SourceSha256);
        }
        Check(File.ReadAllBytes(temp.Journal(target)).SequenceEqual(bytes));
        File.WriteAllBytes(temp.Journal(target), bytes.Take(bytes.Length - 1).ToArray());
        Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, target)).Status == "journal_unavailable");
        Check(File.ReadAllBytes(temp.Journal(target)).SequenceEqual(bytes.Take(bytes.Length - 1)));
    }

    private static void RecoveryExclusive()
    {
        using var temp = new Temp(); var target = Target();
        using (JournalOwner.CreateNew(temp.Root, target)) { }
        var recovery = JournalOwner.OpenRecovery(temp.Root, target);
        using (var child = StartChild("recover", temp.Root, target))
        {
            Check(Line(child) == "ready"); child.StandardInput.WriteLine("go");
            Check(Line(child) == "journal_lease_unavailable"); Check(child.WaitForExit(10000));
        }
        recovery.Dispose(); Throws<ObjectDisposedException>(() => recovery.Get(OperationId));
        using var next = JournalOwner.OpenRecovery(temp.Root, target);
    }

    private static void DistinctProcesses()
    {
        using var temp = new Temp(); var first = Target(); var second = Target(year: "2026");
        using var a = StartChild("create", temp.Root, first); using var b = StartChild("create", temp.Root, second);
        try
        {
            Check(Line(a) == "ready" && Line(b) == "ready");
            a.StandardInput.WriteLine("go"); b.StandardInput.WriteLine("go");
            Check(Line(a) == "owned" && Line(b) == "owned");
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, first)).Status == "journal_lease_unavailable");
            a.StandardInput.WriteLine("exit"); Check(a.WaitForExit(10000));
            using var recovered = JournalOwner.OpenRecovery(temp.Root, first);
            Check(recovered.Get(OperationId) != null);
            Check(Throws<JournalOwnershipException>(() => JournalOwner.OpenRecovery(temp.Root, second)).Status == "journal_lease_unavailable");
            b.StandardInput.WriteLine("exit"); Check(b.WaitForExit(10000));
        }
        finally { Stop(a); Stop(b); }
    }

    private static void CompetingCreators()
    {
        using var temp = new Temp(); var first = Target(); var second = Target(first.JournalId);
        using var a = StartChild("create", temp.Root, first); using var b = StartChild("create", temp.Root, second);
        try
        {
            Check(Line(a) == "ready" && Line(b) == "ready");
            a.StandardInput.WriteLine("go"); b.StandardInput.WriteLine("go");
            var ra = Line(a); var rb = Line(b);
            Check((ra == "owned") != (rb == "owned"), ra + " / " + rb);
            Check(new[] { "journal_exists", "journal_initialization_failed" }.Contains(ra == "owned" ? rb : ra));
            var winner = ra == "owned" ? a : b; var target = ra == "owned" ? first : second;
            var before = File.ReadAllBytes(temp.Metadata(target));
            winner.StandardInput.WriteLine("exit"); Check(winner.WaitForExit(10000));
            using var recovered = JournalOwner.OpenRecovery(temp.Root, target);
            Check(recovered.Get(OperationId) != null && File.ReadAllBytes(temp.Metadata(target)).SequenceEqual(before));
        }
        finally { Stop(a); Stop(b); }
    }

    private static void CrashRecovery()
    {
        using var temp = new Temp(); var target = Target(); using var child = StartChild("create", temp.Root, target);
        try
        {
            Check(Line(child) == "ready"); child.StandardInput.WriteLine("go"); Check(Line(child) == "owned");
            var original = File.ReadAllBytes(temp.Journal(target));
            child.Kill(); Check(child.WaitForExit(10000));
            using var recovery = JournalOwner.OpenRecovery(temp.Root, target);
            Check(recovery.Get(OperationId)!.Receipt == null);
            Check(File.ReadAllBytes(temp.Journal(target)).SequenceEqual(original));
            Check(File.Exists(Path.Combine(temp.DirectoryOf(target), "owner.lock")));
        }
        finally { Stop(child); }
    }

    private static void LegacyGlobals()
    {
        using var temp = new Temp(); Directory.CreateDirectory(temp.Root);
        var journal = Path.Combine(temp.Root, "operations.jsonl"); var discovery = Path.Combine(temp.Root, "discovery.json");
        File.WriteAllText(journal, "legacy archive"); File.WriteAllText(discovery, "old discovery");
        var target = Target(); using (JournalOwner.CreateNew(Path.Combine(temp.Root, "v4"), target)) { }
        using var recovered = JournalOwner.OpenRecovery(Path.Combine(temp.Root, "v4"), target);
        Check(File.ReadAllText(journal) == "legacy archive" && File.ReadAllText(discovery) == "old discovery");
    }

    private static Process StartChild(string mode, string root, ConnectorTarget target)
    {
        var info = new ProcessStartInfo("dotnet") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        foreach (var value in new[] { Assembly.GetExecutingAssembly().Location, "--ownership-child", mode, root, JsonSerializer.Serialize(target) }) info.ArgumentList.Add(value);
        return Process.Start(info)!;
    }
    private static string Line(Process child) => child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(10)).GetAwaiter().GetResult()
        ?? throw new Exception("child closed output: " + child.StandardError.ReadToEnd());
    private static void Stop(Process child) { if (!child.HasExited) { child.Kill(); Check(child.WaitForExit(10000)); } }
    public static int Child(string[] args)
    {
        try
        {
            var target = JsonSerializer.Deserialize<ConnectorTarget>(args[3])!;
            Console.WriteLine("ready"); Console.ReadLine();
            if (args[1] == "recover") { using var recovery = JournalOwner.OpenRecovery(args[2], target); Console.WriteLine("recovered"); }
            else
            {
                using var owner = JournalOwner.CreateNew(args[2], target);
                Check(owner.Journal.TryStart(Input(owner.Target), out _)); Console.WriteLine("owned"); Console.ReadLine();
            }
            return 0;
        }
        catch (JournalOwnershipException error) { Console.WriteLine(error.Status); return 0; }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
