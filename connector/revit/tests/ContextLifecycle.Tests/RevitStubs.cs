// Deliberately NOT a Revit simulator. A native identity is separate from each
// wrapper; collisions and failing API access exercise production boundaries.
using System;
using System.Collections.Generic;

namespace Autodesk.Revit.DB
{
    internal sealed class NativeDocument
    {
        public bool Valid = true;
        public string Title = "Project";
        public string Path = "";
        public int Hash = 17;
        public int Mutations;
    }

    public sealed class Document
    {
        internal NativeDocument Native { get; }
        internal bool ThrowEquals = false;
        internal bool ThrowValidity = false;
        internal Document(NativeDocument native) { Native = native; }
        public bool IsValidObject => ThrowValidity ? throw new InvalidOperationException("validity probe failed") : Native.Valid;
        public string Title => Native.Title;
        public string PathName => Native.Path;
        public View ActiveView { get; set; } = new View();
        public bool IsFamilyDocument { get; set; }
        public bool IsReadOnly { get; set; }
        public bool IsModifiable { get; set; }
        public Action? MutationHook { get; set; }
        public void TestMutation() { Native.Mutations++; MutationHook?.Invoke(); }
        public override int GetHashCode() => Native.Hash;
        public override bool Equals(object? other) => ThrowEquals
            ? throw new InvalidOperationException("native equality failed")
            : other is Document document && object.ReferenceEquals(Native, document.Native);
    }

    public sealed class ElementId
    {
        public long Value { get; }
        public int IntegerValue => checked((int)Value);
        public ElementId(long value) { Value = value; }
    }

    public sealed class View { public ElementId Id { get; set; } = new ElementId(1); }
}

namespace Autodesk.Revit.DB.Events
{
    public sealed class DocumentClosedEventArgs : EventArgs { }
    public sealed class DocumentChangedEventArgs : EventArgs
    {
        private readonly DB.Document _document;
        public List<DB.ElementId> Added { get; } = new List<DB.ElementId>();
        public List<DB.ElementId> Modified { get; } = new List<DB.ElementId>();
        public List<DB.ElementId> Deleted { get; } = new List<DB.ElementId>();
        public List<string> Transactions { get; } = new List<string>();
        public DocumentChangedEventArgs(DB.Document document) { _document = document; }
        public DB.Document GetDocument() => _document;
        public ICollection<DB.ElementId> GetAddedElementIds() => Added;
        public ICollection<DB.ElementId> GetModifiedElementIds() => Modified;
        public ICollection<DB.ElementId> GetDeletedElementIds() => Deleted;
        public IList<string> GetTransactionNames() => Transactions;
    }
}

namespace Autodesk.Revit.ApplicationServices
{
    public class ControlledApplication
    {
        public string VersionNumber { get; set; } = "2026";
        public event EventHandler<DB.Events.DocumentChangedEventArgs>? DocumentChanged;
        public event EventHandler<DB.Events.DocumentClosedEventArgs>? DocumentClosed;
        public int Listeners => (DocumentChanged?.GetInvocationList().Length ?? 0)
                                + (DocumentClosed?.GetInvocationList().Length ?? 0);
        public void Changed(DB.Document document, string operation = "commit")
        {
            var args = new DB.Events.DocumentChangedEventArgs(document);
            args.Transactions.Add(operation);
            DocumentChanged?.Invoke(this, args);
        }
        public void Closed() => DocumentClosed?.Invoke(this, new DB.Events.DocumentClosedEventArgs());
    }
    public sealed class Application : ControlledApplication { }
}

namespace Autodesk.Revit.UI
{
    public enum Result { Succeeded, Failed, Cancelled }
    public interface IExternalApplication
    {
        Result OnStartup(UIControlledApplication application);
        Result OnShutdown(UIControlledApplication application);
    }
    public sealed class UIControlledApplication
    {
        public ApplicationServices.ControlledApplication ControlledApplication { get; } = new ApplicationServices.ControlledApplication();
        public void CreateRibbonTab(string name) { }
        public RibbonPanel CreateRibbonPanel(string tab, string name) => new RibbonPanel();
    }
    public sealed class RibbonPanel { public void AddItem(PushButtonData button) { } }
    public sealed class PushButtonData
    {
        public PushButtonData(string name, string text, string assembly, string command) { }
        public string ToolTip { get; set; } = "";
        public string LongDescription { get; set; } = "";
    }
    public interface IExternalEventHandler
    {
        void Execute(UIApplication application);
        string GetName();
    }
    public enum ExternalEventRequest { Accepted, Pending, Denied }
    // Only the API event dispatch is stubbed. The linked production schedulers
    // own their real queues and exception/completion handling.
    public sealed class ExternalEvent : IDisposable
    {
        private static readonly List<ExternalEvent> Events = new List<ExternalEvent>();
        public static ExternalEventRequest? NextRaise;
        private readonly IExternalEventHandler _handler;
        private bool _pending;
        private ExternalEvent(IExternalEventHandler handler) { _handler = handler; Events.Add(this); }
        public static ExternalEvent Create(IExternalEventHandler handler) => new ExternalEvent(handler);
        public ExternalEventRequest Raise()
        {
            var result = NextRaise ?? (_pending ? ExternalEventRequest.Pending : ExternalEventRequest.Accepted);
            NextRaise = null;
            if (result == ExternalEventRequest.Accepted || result == ExternalEventRequest.Pending) _pending = true;
            return result;
        }
        public static void PumpAll(UIApplication application)
        {
            for (var count = 0; count < 1000; count++)
            {
                var item = Events.Find(candidate => candidate._pending);
                if (item == null) return;
                item._pending = false;
                item._handler.Execute(application);
            }
            throw new InvalidOperationException("test event dispatch did not drain");
        }
        public void Dispose() { Events.Remove(this); }
    }
    public sealed class UIApplication
    {
        public ApplicationServices.Application Application { get; } = new ApplicationServices.Application();
        public UIDocument ActiveUIDocument { get; set; } = null!;
    }
    public sealed class UIDocument
    {
        public DB.Document Document { get; }
        public Selection Selection { get; } = new Selection();
        public UIDocument(DB.Document document) { Document = document; }
    }
    public sealed class Selection
    {
        public List<DB.ElementId> Ids { get; } = new List<DB.ElementId>();
        public ICollection<DB.ElementId> GetElementIds() => Ids;
    }
}
