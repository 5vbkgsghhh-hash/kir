using System;
using System.Collections.Generic;
using System.Globalization;
using System.Threading;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Events;

namespace Kir.Revit.Connector.Context
{
    internal sealed class DocumentRevisionTracker : IDisposable
    {
        private readonly ControlledApplication _application;
        private readonly int _apiThread = Thread.CurrentThread.ManagedThreadId;
        private readonly string _epoch = Guid.NewGuid().ToString("N");
        private readonly List<Entry> _entries = new List<Entry>();
        private long _nextDocument;
        private Exception? _failure;
        private bool _disposed;

        private sealed class Entry
        {
            public Document Document { get; }
            public string Key { get; }
            public long Revision;

            public Entry(Document document, string key) { Document = document; Key = key; }
        }

        public DocumentRevisionTracker(ControlledApplication application)
        {
            _application = application ?? throw new ArgumentNullException(nameof(application));
            _application.DocumentChanged += OnDocumentChanged;
            _application.DocumentClosed += OnDocumentClosed;
        }

        /// <summary>
        /// A snapshot of one open native document, not a file or a persisted
        /// BIM identity. Revit calls and state access stay on the API thread;
        /// no other callback can advance the counter between these two fields.
        /// A missed/failed event poisons this tracker until add-in restart.
        /// </summary>
        public DocumentState GetState(Document document)
        {
            EnsureUsable();
            try
            {
                var entry = FindOrCreate(document);
                return new DocumentState(entry.Key, entry.Revision);
            }
            catch (Exception ex)
            {
                Fail(ex);
                throw Unavailable();
            }
        }

        public long Get(Document document) => GetState(document).Revision;

        /// <summary>
        /// Revit Document.Equals compares the underlying open document, even
        /// through different managed wrappers. ReferenceEquals and bare int
        /// hashes do not implement that contract. Call only on the API thread.
        /// </summary>
        internal static bool SameDocument(Document left, Document right)
        {
            if (left == null || right == null || !left.IsValidObject || !right.IsValidObject)
                throw new InvalidOperationException("document identity is unavailable for an invalid document");
            return left.Equals(right);
        }

        private Entry FindOrCreate(Document document)
        {
            PruneInvalid();
            if (document == null || !document.IsValidObject)
                throw new InvalidOperationException("cannot observe an invalid document");
            foreach (var entry in _entries)
                if (SameDocument(entry.Document, document)) return entry;
            // The epoch changes with the App-lifetime tracker, not each
            // ten-minute connector session. No title/path/hash is an owner.
            var key = _epoch + checked(++_nextDocument).ToString("x16", CultureInfo.InvariantCulture);
            var created = new Entry(document, key);
            _entries.Add(created);
            return created;
        }

        private void PruneInvalid()
        {
            for (var index = _entries.Count - 1; index >= 0; index--)
                if (!_entries[index].Document.IsValidObject) _entries.RemoveAt(index);
        }

        private void OnDocumentChanged(object? sender, DocumentChangedEventArgs args)
        {
            try
            {
                EnsureUsable();
                var entry = FindOrCreate(args.GetDocument());
                entry.Revision = checked(entry.Revision + 1);
            }
            catch (Exception ex) { Fail(ex); }
        }

        private void OnDocumentClosed(object? sender, DocumentClosedEventArgs args)
        {
            // Do not retire on DocumentClosing: a subsequent cancellation
            // leaves the document alive. Closed-event IDs only pair events;
            // they are not document identities.
            try { EnsureUsable(); PruneInvalid(); }
            catch (Exception ex) { Fail(ex); }
        }

        private void EnsureUsable()
        {
            if (Thread.CurrentThread.ManagedThreadId != _apiThread)
                throw new InvalidOperationException("document tracking requires the Revit API thread");
            if (_disposed) throw new ObjectDisposedException(nameof(DocumentRevisionTracker));
            if (_failure != null) throw Unavailable();
        }

        private void Fail(Exception error) { if (_failure == null) _failure = error; }

        private InvalidOperationException Unavailable() =>
            new InvalidOperationException("document revision tracking is unavailable; restart the add-in before executing", _failure);

        public void Dispose()
        {
            if (_disposed) return;
            _application.DocumentChanged -= OnDocumentChanged;
            _application.DocumentClosed -= OnDocumentClosed;
            _entries.Clear();
            _disposed = true;
        }
    }

    internal sealed class DocumentState
    {
        public string DocumentKey { get; }
        public long Revision { get; }

        internal DocumentState(string documentKey, long revision)
        {
            DocumentKey = documentKey;
            Revision = revision;
        }
    }
}
