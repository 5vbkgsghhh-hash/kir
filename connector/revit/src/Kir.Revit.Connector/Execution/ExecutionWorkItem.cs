using System;
using System.Threading.Tasks;
using Kir.Revit.Protocol;

namespace Kir.Revit.Connector.Execution
{
    internal sealed class ExecutionWorkItem
    {
        private readonly byte[] _assemblyBytes;
        public OperationInputBinding Input { get; }
        public SessionAdmission Admission { get; }
        public string OperationId => Input.OperationId;
        public string SourceSha256 => Input.SourceSha256;
        public byte[] AssemblyBytes => (byte[])_assemblyBytes.Clone();
        public ContextPrecondition Precondition => Input.ToPrecondition();
        public TaskCompletionSource<OperationReceipt> Completion { get; } =
            new TaskCompletionSource<OperationReceipt>(TaskCreationOptions.RunContinuationsAsynchronously);

        public ExecutionWorkItem(OperationInputBinding input, byte[] assemblyBytes, SessionAdmission admission)
        {
            Admission = admission ?? throw new ArgumentNullException(nameof(admission));
            Input = input ?? throw new ArgumentNullException(nameof(input));
            if (assemblyBytes == null || assemblyBytes.Length == 0) throw new ArgumentException("assembly bytes are required");
            _assemblyBytes = (byte[])assemblyBytes.Clone();
        }
    }
}
