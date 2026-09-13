using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace Kir.Revit.Connector.Commands
{
    [Transaction(TransactionMode.Manual)]
    public sealed class ToggleConnectorCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            var app = App.Instance;
            if (app == null) { message = "KIR connector is not initialized."; return Result.Failed; }
            if (app.IsEnabled)
            {
                app.Disable();
                TaskDialog.Show("KIR Connector", "This process's connector session is disabled. Work not yet admitted to start is cancelled; an already started invocation is not interrupted. Durable receipts are retained.");
                return Result.Succeeded;
            }

            var dialog = new TaskDialog("Enable KIR Connector")
            {
                MainInstruction = "Allow a trusted local KIR client to submit generated Revit code for ten minutes?",
                MainContent = "Code is compiled in an isolated local process and executed through Revit's ExternalEvent API. It can modify the active model. No internet listener is opened.",
                CommonButtons = TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No,
                DefaultButton = TaskDialogResult.No,
            };
            if (dialog.Show() != TaskDialogResult.Yes) return Result.Cancelled;
            try
            {
                var until = app.Enable();
                TaskDialog.Show("KIR Connector", "Enabled for the current Windows user until " + until + ".");
                return Result.Succeeded;
            }
            catch (System.Exception ex)
            {
                app.Disable();
                message = ex.Message;
                return Result.Failed;
            }
        }
    }
}
