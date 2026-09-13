using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Protocol;
using Kir.Revit.Connector;
using Kir.Revit.Connector.Context;
using Kir.Revit.Connector.Execution;

// Actual protocol/service/journal fixture. Seeds explicitly artificial KIR
// result evidence in a temporary real journal, then replays via the service.
// No generated assembly is compiled/invoked and no Revit process is launched.
internal static class Program
{
    private static ConnectorRequest Request(JsonElement value)
    {
        var bytes = Encoding.UTF8.GetBytes(value.GetRawText());
        using var framed = new MemoryStream();
        var length = BitConverter.GetBytes(bytes.Length);
        if (!BitConverter.IsLittleEndian) Array.Reverse(length);
        framed.Write(length); framed.Write(bytes); framed.Position = 0;
        return JsonFraming.Read<ConnectorRequest>(framed);
    }

    private static int Main()
    {
        var directory = Path.Combine(Path.GetTempPath(), "kir-protocol-replay-" + Guid.NewGuid().ToString("N"));
        JournalOwner? owner = null;
        try
        {
            using var fixture = JsonDocument.Parse(Console.In.ReadToEnd());
            var root = fixture.RootElement;
            var seed = Request(root.GetProperty("seed"));
            var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(seed.Source!))).ToLowerInvariant();
            if (hash != seed.SourceSha256) throw new InvalidDataException("fixture seed source hash mismatch");
            var input = OperationInputBinding.Capture(seed.OperationId!, seed.SourceSha256!, seed.Precondition!, seed.Target!);
            owner = JournalOwner.CreateNew(directory, input.Target);
            var startedOnly = root.TryGetProperty("started_only", out var only) && only.GetBoolean();
            if (!owner.Journal.TryStart(input, out _)) throw new InvalidDataException("fixture start was not new");
            if (!startedOnly)
            {
                var resultJson = root.GetProperty("result_json").GetString();
                owner.Journal.AppendTerminal(input, new OperationReceipt
                {
                    Target = input.Target, OperationId = input.OperationId,
                    SourceSha256 = input.SourceSha256, DocumentKey = input.DocumentKey,
                    Precondition = input.ToPrecondition(), State = ReceiptStates.InvocationCompleted,
                    Started = true, MayRetry = false, TransactionEvidence = "changes_not_observed",
                    ResultJson = resultJson, Changes = new ChangeManifest(),
                    TimestampUtc = DateTime.UtcNow.ToString("O"),
                });
            }
            var serviceTarget = root.GetProperty("service_target").Deserialize<ConnectorTarget>()!;
            if (!serviceTarget.Matches(owner.Target))
            {
                owner.Dispose();
                owner = JournalOwner.CreateNew(directory, serviceTarget);
            }
            // Replay defaults to no active document. A separate explicitly
            // stubbed context scenario exercises the real collector/scheduler,
            // not a native document or a generated-code invocation.
            var ui = new UIApplication();
            ui.Application.VersionNumber = serviceTarget.RevitVersion;
            using var tracker = new DocumentRevisionTracker(ui.Application);
            if (root.TryGetProperty("context_scenario", out var contextScenario))
            {
                var scenario = contextScenario.GetString();
                if (scenario != "none")
                {
                    if (scenario != "document" && scenario != "family" && scenario != "read_only" && scenario != "modifiable")
                        throw new InvalidDataException("unknown fixture context scenario");
                    var document = new Document(new NativeDocument { Title = "Башня 😀" })
                    {
                        ActiveView = new View { Id = new ElementId(31) },
                        IsFamilyDocument = scenario == "family", IsReadOnly = scenario == "read_only",
                        IsModifiable = scenario == "modifiable",
                    };
                    ui.ActiveUIDocument = new UIDocument(document);
                    ui.ActiveUIDocument.Selection.Ids.Add(new ElementId(42));
                    ui.ActiveUIDocument.Selection.Ids.Add(new ElementId(17));
                    ui.Application.Changed(document); ui.Application.Changed(document);
                }
            }
            var collector = new ContextSnapshotCollector(tracker);
            using var context = new ContextQueryScheduler(collector);
            using var queue = new ExternalEventScheduler(new ExecutionEngine(collector, owner.Journal));
            var admission = new SessionAdmission(root.GetProperty("session_id").GetString()!, DateTime.UtcNow.AddHours(1));
            var service = new ConnectorService(root.GetProperty("token").GetString()!, admission,
                context, queue, new CompilerHostClient(directory), owner.Journal, serviceTarget,
                directory);
            var frames = new List<string>();
            foreach (var value in root.GetProperty("requests").EnumerateArray())
            {
                var pending = service.Handle(Request(value));
                // Real Capture waits for a Revit ExternalEvent; only API event
                // dispatch is stubbed by this fixture. No native success claim.
                ExternalEvent.PumpAll(ui);
                var response = pending.GetAwaiter().GetResult();
                using var wire = new MemoryStream();
                JsonFraming.Write(wire, response);
                frames.Add(Convert.ToBase64String(wire.ToArray()));
            }
            var discovery = new DiscoveryRecord
            {
                Target = serviceTarget, SessionId = admission.SessionId,
                PipeName = "kir-revit-123-aaaaaaaaaaaaaaaaaaaaaaaa", Token = root.GetProperty("token").GetString()!,
                ProcessId = 123, ExpiresUtc = admission.ExpiresUtc.ToString("O", CultureInfo.InvariantCulture),
            };
            Console.WriteLine(JsonSerializer.Serialize(new { scope = "seeded_receipt_replay_not_invocation", frames,
                discovery_utf8_base64 = Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(discovery)) }));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 2;
        }
        finally
        {
            owner?.Dispose();
            if (Directory.Exists(directory)) Directory.Delete(directory, true);
        }
    }
}
