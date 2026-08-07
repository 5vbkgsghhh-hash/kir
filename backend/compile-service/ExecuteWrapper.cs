using System.Text;

namespace CompileService;

/// <summary>
/// Byte-for-byte C# counterpart of kukai.compiler_unit.wrap_execute_body.
/// KIR supplies an Execute body; Roslyn receives this complete source unit.
/// </summary>
internal static class ExecuteWrapper
{
    internal const string Contract = "kukai-revit-execute-wrapper/1";

    internal const string Header =
        "using System;\n" +
        "using System.Linq;\n" +
        "using System.Collections.Generic;\n" +
        "using System.Text;\n" +
        "using System.Text.RegularExpressions;\n" +
        "using Autodesk.Revit.DB;\n" +
        "using Autodesk.Revit.DB.Architecture;\n" +
        "using Autodesk.Revit.DB.Structure;\n" +
        "using Autodesk.Revit.DB.Mechanical;\n" +
        "using Autodesk.Revit.DB.Electrical;\n" +
        "using Autodesk.Revit.DB.Plumbing;\n" +
        "using Autodesk.Revit.UI;\n" +
        "\n" +
        "namespace Kukai\n" +
        "{\n" +
        "    public class UserCode\n" +
        "    {\n" +
        "        public static object Execute(Document doc, UIDocument uidoc)\n" +
        "        {\n";

    internal const string Footer =
        "\n" +
        "        }\n" +
        "    }\n" +
        "}\n";

    internal static string Wrap(string source)
    {
        ArgumentNullException.ThrowIfNull(source);
        var lines = source.Split('\n');
        var result = new StringBuilder(
            Header.Length + source.Length + Footer.Length + lines.Length * 12);
        result.Append(Header);
        for (var index = 0; index < lines.Length; index++)
        {
            var line = lines[index];
            if (!IsPythonWhitespaceOnly(line))
                result.Append("            ");
            result.Append(line);
            if (index + 1 < lines.Length)
                result.Append('\n');
        }
        result.Append(Footer);
        return result.ToString();
    }

    // Python str.strip() recognises four C0 separators that .NET historically
    // did not. Enumerating Python's whitespace set keeps blank-line indentation
    // byte-identical even for adversarial Unicode input.
    private static bool IsPythonWhitespaceOnly(string value)
    {
        foreach (var character in value)
        {
            if (character is >= '\u0009' and <= '\u000d' ||
                character is >= '\u001c' and <= '\u0020' ||
                character is '\u0085' or '\u00a0' or '\u1680' or
                    '\u2028' or '\u2029' or '\u202f' or '\u205f' or '\u3000' ||
                character is >= '\u2000' and <= '\u200a')
            {
                continue;
            }
            return false;
        }
        return true;
    }
}
