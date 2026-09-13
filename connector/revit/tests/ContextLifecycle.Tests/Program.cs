using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;
using Autodesk.Revit.UI;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;
using Kir.Revit.Protocol;

internal static class Program
{
    private static readonly (string Name, Action Run)[] Cases =
    {
        ("different wrappers share token and revision", Wrappers),
        ("equal hashes do not merge documents", HashCollision),
        ("Save As changes metadata, not identity", SaveAs),
        ("close/reopen gets new token and prunes old wrapper", Reopen),
        ("cancelled closing leaves a valid document unchanged", CancelledClose),
        ("commit undo redo monotonically advance observed revision", Revisions),
        ("changes before first capture are counted", BeforeCapture),
        ("new tracker epoch rejects previous process token", Epoch),
        ("invalid document fails closed", InvalidDocument),
        ("invalid change event cannot silently reset revision", InvalidChange),
        ("equality failure latches unavailable", EqualityFailure),
        ("validity failure latches unavailable", ValidityFailure),
        ("revision overflow latches unavailable", Overflow),
        ("token sequence overflow latches unavailable", TokenOverflow),
        ("wrong thread cannot access Revit document state", WrongThread),
        ("disposal releases subscriptions and refuses further captures", Disposal),
        ("collector captures token/revision and stable selection digest", Collector),
        ("matches rejects incomplete snapshot and stale supplied fields", Preconditions),
        ("capture failure is not a complete revision-zero snapshot", CaptureFailure),
        ("manifest captures different wrapper of the expected document", Manifest),
        ("manifest ignores distinct native document with equal hash", ForeignManifest),
        ("manifest refuses invalid document rather than silently skipping", InvalidManifest),
    };

    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--ownership-child") return JournalOwnershipTests.Child(args);
        if (args.Length > 0 && args[0] == "--session-child") return SessionLifecycleTests.Child(args);
        var failed = 0;
        var cases = args.Length == 1 && args[0] == "--cancellation-only" ? CancellationTests.Cases :
            Cases.Concat(ExecutionBindingTests.Cases).Concat(JournalOwnershipTests.Cases).Concat(SessionLifecycleTests.Cases).Concat(CancellationTests.Cases).ToArray();
        foreach (var test in cases)
        {
            try { test.Run(); Console.WriteLine("PASS " + test.Name); }
            catch (Exception error) { failed++; Console.Error.WriteLine("FAIL " + test.Name + ": " + error); }
        }
        Console.WriteLine($"{cases.Length - failed} passed, {failed} failed; headless stubs, no Revit execution");
        return failed == 0 ? 0 : 1;
    }

    private static Document Doc() => new Document(new NativeDocument());
    private static void Check(bool value, string message = "assertion failed")
    { if (!value) throw new Exception(message); }
    private static T Throws<T>(Action action) where T : Exception
    {
        try { action(); } catch (T error) { return error; }
        throw new Exception("expected " + typeof(T).Name);
    }
    private static IList Entries(DocumentRevisionTracker tracker) =>
        (IList)typeof(DocumentRevisionTracker).GetField("_entries", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(tracker)!;
    private static void Wrappers()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app);
        var a = Doc(); var b = new Document(a.Native);
        Check(!object.ReferenceEquals(a, b) && a.Equals(b));
        var before = tracker.GetState(a); app.Changed(b);
        var after = tracker.GetState(b);
        Check(before.DocumentKey == after.DocumentKey && before.Revision == 0 && after.Revision == 1);
        Check(Entries(tracker).Count == 1);
    }
    private static void HashCollision()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app);
        var a = Doc(); var b = Doc(); Check(a.GetHashCode() == b.GetHashCode() && !a.Equals(b));
        var first = tracker.GetState(a); var second = tracker.GetState(b); app.Changed(b);
        Check(first.DocumentKey != second.DocumentKey);
        Check(tracker.GetState(a).Revision == 0 && tracker.GetState(b).Revision == 1);
    }
    private static void SaveAs()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app);
        var document = Doc(); var before = tracker.GetState(document);
        document.Native.Title = "Renamed"; document.Native.Path = @"C:\different\renamed.rvt";
        var after = tracker.GetState(new Document(document.Native));
        Check(before.DocumentKey == after.DocumentKey && before.Revision == after.Revision);
    }
    private static void Reopen()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app);
        var old = Doc(); old.Native.Path = @"C:\test\model.rvt";
        var before = tracker.GetState(old); old.Native.Valid = false; app.Closed();
        Check(Entries(tracker).Count == 0);
        var reopened = Doc(); reopened.Native.Path = old.Native.Path; reopened.Native.Hash = 18;
        var next = tracker.GetState(reopened);
        Check(next.DocumentKey != before.DocumentKey && next.Revision == 0);
    }
    private static void CancelledClose()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app);
        var document = Doc(); var before = tracker.GetState(document);
        // Failed/cancelled post-close notification must not retire a live entry.
        app.Closed(); Check(tracker.GetState(document).DocumentKey == before.DocumentKey);
    }
    private static void Revisions()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc();
        var before = tracker.GetState(document); long revision = 0;
        foreach (var operation in new[] { "commit", "undo", "redo" })
        { app.Changed(new Document(document.Native), operation); Check(tracker.GetState(document).Revision == ++revision); }
        Check(before.Revision == 0, "returned state must not alias the mutable counter");
    }
    private static void BeforeCapture()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc();
        app.Changed(document); Check(tracker.GetState(document).Revision == 1);
    }
    private static void Epoch()
    {
        var app = new ControlledApplication(); var document = Doc(); string previous;
        using (var first = new DocumentRevisionTracker(app)) previous = first.GetState(document).DocumentKey;
        using var second = new DocumentRevisionTracker(app); Check(second.GetState(document).DocumentKey != previous);
    }
    private static void InvalidDocument()
    {
        using var tracker = new DocumentRevisionTracker(new ControlledApplication()); var document = Doc(); document.Native.Valid = false;
        Throws<InvalidOperationException>(() => tracker.GetState(document));
        Throws<InvalidOperationException>(() => tracker.GetState(Doc()));
    }
    private static void InvalidChange()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc();
        tracker.GetState(document); document.Native.Valid = false; app.Changed(document);
        Throws<InvalidOperationException>(() => tracker.GetState(Doc()));
    }
    private static void EqualityFailure()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc();
        tracker.GetState(document); document.ThrowEquals = true; app.Changed(new Document(document.Native));
        document.ThrowEquals = false; Throws<InvalidOperationException>(() => tracker.GetState(document));
    }
    private static void ValidityFailure()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc();
        tracker.GetState(document); document.ThrowValidity = true; app.Closed();
        document.ThrowValidity = false; Throws<InvalidOperationException>(() => tracker.GetState(document));
    }
    private static void Overflow()
    {
        var app = new ControlledApplication(); using var tracker = new DocumentRevisionTracker(app); var document = Doc(); tracker.GetState(document);
        var entry = Entries(tracker)[0]!; entry.GetType().GetField("Revision")!.SetValue(entry, long.MaxValue);
        app.Changed(document);
        var error = Throws<InvalidOperationException>(() => tracker.GetState(document));
        Check(error.InnerException is OverflowException);
    }
    private static void TokenOverflow()
    {
        using var tracker = new DocumentRevisionTracker(new ControlledApplication());
        typeof(DocumentRevisionTracker).GetField("_nextDocument", BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(tracker, long.MaxValue);
        var error = Throws<InvalidOperationException>(() => tracker.GetState(Doc()));
        Check(error.InnerException is OverflowException);
        Throws<InvalidOperationException>(() => tracker.GetState(Doc()));
    }
    private static void WrongThread()
    {
        using var tracker = new DocumentRevisionTracker(new ControlledApplication()); var document = Doc(); Exception? failure = null;
        var thread = new Thread(() => { try { tracker.GetState(document); } catch (Exception error) { failure = error; } });
        thread.Start(); Check(thread.Join(5000)); Check(failure is InvalidOperationException);
        Check(Entries(tracker).Count == 0); Check(tracker.GetState(document).Revision == 0);
    }
    private static void Disposal()
    {
        var app = new ControlledApplication(); var tracker = new DocumentRevisionTracker(app); tracker.GetState(Doc());
        Check(app.Listeners == 2); tracker.Dispose(); tracker.Dispose();
        Check(app.Listeners == 0 && Entries(tracker).Count == 0);
        Throws<ObjectDisposedException>(() => tracker.GetState(Doc()));
    }
    private static void Collector()
    {
        var ui = new UIApplication(); using var tracker = new DocumentRevisionTracker(ui.Application); var collector = new ContextSnapshotCollector(tracker);
        var empty = collector.Capture(ui); Check(empty.Complete && !empty.HasDocument);
        var document = Doc(); ui.ActiveUIDocument = new UIDocument(document);
        ui.ActiveUIDocument.Selection.Ids.AddRange(new[] { new ElementId(9), new ElementId(2) });
        var first = collector.Capture(ui); ui.Application.Changed(new Document(document.Native));
        ui.ActiveUIDocument = new UIDocument(new Document(document.Native));
        ui.ActiveUIDocument.Selection.Ids.AddRange(new[] { new ElementId(2), new ElementId(9) });
        var second = collector.Capture(ui);
        Check(first.DocumentKey == second.DocumentKey && second.Revision == 1);
        Check(first.SelectionDigest == second.SelectionDigest && first.SelectionCount == 2 && second.Complete);
    }
    private static void Preconditions()
    {
        var snapshot = new ContextSnapshot { HasDocument = true, Complete = true, DocumentKey = "opaque", Revision = 3, ActiveViewId = 7, SelectionDigest = "selection" };
        var expected = new ContextPrecondition { DocumentKey = "opaque", Revision = 3, ActiveViewId = 7, SelectionDigest = "selection" };
        Check(ContextSnapshotCollector.Matches(snapshot, expected)); snapshot.Complete = false;
        Check(!ContextSnapshotCollector.Matches(snapshot, expected)); snapshot.Complete = true; snapshot.HasDocument = false;
        Check(!ContextSnapshotCollector.Matches(snapshot, expected)); snapshot.HasDocument = true; expected.DocumentKey = "other";
        Check(!ContextSnapshotCollector.Matches(snapshot, expected)); expected.DocumentKey = "opaque"; expected.Revision = 2;
        Check(!ContextSnapshotCollector.Matches(snapshot, expected)); expected.Revision = 3; expected.ActiveViewId = 8;
        Check(!ContextSnapshotCollector.Matches(snapshot, expected)); expected.ActiveViewId = 7; expected.SelectionDigest = "different";
        Check(!ContextSnapshotCollector.Matches(snapshot, expected));
        // This low-level matcher still accepts partial conditions. Execution
        // cannot use a missing revision: OperationInputBinding validates it.
        Check(ContextSnapshotCollector.Matches(snapshot, new ContextPrecondition { DocumentKey = "opaque" }));
    }
    private static void CaptureFailure()
    {
        var ui = new UIApplication(); using var tracker = new DocumentRevisionTracker(ui.Application); var collector = new ContextSnapshotCollector(tracker);
        var document = Doc(); ui.ActiveUIDocument = new UIDocument(document); collector.Capture(ui);
        document.ThrowEquals = true; ui.Application.Changed(new Document(document.Native)); document.ThrowEquals = false;
        Throws<InvalidOperationException>(() => collector.Capture(ui));
    }
    private static void CaptureManifest(Document expected, Document actual, ChangeManifest manifest)
    {
        var args = new DocumentChangedEventArgs(actual); args.Added.Add(new ElementId(41)); args.Modified.Add(new ElementId(42));
        args.Deleted.Add(new ElementId(43)); args.Transactions.Add("T");
        typeof(ExecutionEngine).GetMethod("CaptureChanges", BindingFlags.Static | BindingFlags.NonPublic)!
            .Invoke(null, new object[] { expected, args, manifest });
    }
    private static void Manifest()
    {
        var document = Doc(); var manifest = new ChangeManifest(); CaptureManifest(document, new Document(document.Native), manifest);
        Check(manifest.Added[0] == 41 && manifest.Modified[0] == 42 && manifest.Deleted[0] == 43 && manifest.TransactionNames[0] == "T");
    }
    private static void ForeignManifest()
    {
        var manifest = new ChangeManifest(); CaptureManifest(Doc(), Doc(), manifest); Check(manifest.IsEmpty && manifest.TransactionNames.Count == 0);
    }
    private static void InvalidManifest()
    {
        var document = Doc(); document.Native.Valid = false;
        var error = Throws<TargetInvocationException>(() => CaptureManifest(document, document, new ChangeManifest()));
        Check(error.InnerException is InvalidOperationException);
    }
}
