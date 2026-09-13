using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Kir.Revit.Connector.Compat;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Context
{
    internal sealed class ContextSnapshotCollector
    {
        private readonly DocumentRevisionTracker _revisions;

        public ContextSnapshotCollector(DocumentRevisionTracker revisions) => _revisions = revisions;

        public ContextSnapshot Capture(UIApplication application)
        {
            var uiDocument = application.ActiveUIDocument;
            var document = uiDocument?.Document;
            if (document == null)
                return new ContextSnapshot { HasDocument = false, Complete = true, RevitVersion = application.Application.VersionNumber };

            var state = _revisions.GetState(document);
            var selection = uiDocument!.Selection.GetElementIds()
                .Select(RevitCompat.IdValue).OrderBy(value => value).ToList();
            return new ContextSnapshot
            {
                HasDocument = true,
                DocumentKey = state.DocumentKey,
                DocumentTitle = document.Title ?? string.Empty,
                RevitVersion = application.Application.VersionNumber ?? string.Empty,
                Revision = state.Revision,
                ActiveViewId = document.ActiveView == null ? 0 : RevitCompat.IdValue(document.ActiveView.Id),
                SelectionDigest = Digest(selection),
                SelectionCount = selection.Count,
                IsFamilyDocument = document.IsFamilyDocument,
                IsReadOnly = document.IsReadOnly,
                IsModifiable = document.IsModifiable,
                Complete = true,
            };
        }

        public static bool Matches(ContextSnapshot snapshot, ContextPrecondition precondition)
        {
            if (!snapshot.Complete || !snapshot.HasDocument || !string.Equals(snapshot.DocumentKey, precondition.DocumentKey, StringComparison.Ordinal)) return false;
            if (precondition.Revision.HasValue && snapshot.Revision != precondition.Revision.Value) return false;
            if (precondition.ActiveViewId.HasValue && snapshot.ActiveViewId != precondition.ActiveViewId.Value) return false;
            return precondition.SelectionDigest == null
                   || string.Equals(snapshot.SelectionDigest, precondition.SelectionDigest, StringComparison.Ordinal);
        }

        private static string Digest(IEnumerable<long> values) =>
            Sha256(Encoding.UTF8.GetBytes(string.Join(",", values)));

        private static string Sha256(byte[] bytes)
        {
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(bytes)).Replace("-", string.Empty).ToLowerInvariant();
        }
    }
}
