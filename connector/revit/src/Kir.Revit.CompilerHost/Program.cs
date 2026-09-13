using System;
using Kir.Revit.Protocol;

namespace Kir.Revit.CompilerHost
{
    internal static class Program
    {
        public static int Main()
        {
            CompilerResponse response;
            try
            {
                var request = JsonFraming.ReadCompilerRequest(Console.OpenStandardInput());
                response = Compiler.Compile(request);
            }
            catch (Exception ex)
            {
                response = new CompilerResponse
                {
                    Ok = false,
                    Diagnostics = { "compiler_host: " + ex.Message },
                };
            }

            try
            {
                JsonFraming.Write(Console.OpenStandardOutput(), response);
                return response.Ok ? 0 : 2;
            }
            catch
            {
                return 3;
            }
        }
    }
}
