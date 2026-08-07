using CompileService;

var builder = WebApplication.CreateBuilder(args);

// Default port 52412, overridable via config/env
builder.WebHost.UseUrls(
    builder.Configuration.GetValue("Urls", "http://localhost:52412")!);

builder.Services.AddSingleton<RoslynCompiler>();

// CORS: localhost only
builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.SetIsOriginAllowed(origin =>
        {
            var uri = new Uri(origin);
            return uri.Host is "localhost" or "127.0.0.1";
        })
        .AllowAnyHeader()
        .AllowAnyMethod();
    });
});

var app = builder.Build();
app.UseCors();

// Force initialization at startup (preload all references)
var compiler = app.Services.GetRequiredService<RoslynCompiler>();

HealthResponse BuildHealthResponse()
{
    var failed = RoslynCompiler.FailedReferences
        .Select(f => new FailedReferenceDto(f.Path, f.Category, f.Error, f.Timestamp))
        .ToList();
    var ready = failed.Count == 0
        && compiler.MissingVersions.Count == 0
        && compiler.SystemReferenceSetsReady;

    return new HealthResponse(
        Status: ready ? "ready" : "degraded",
        Versions: compiler.AvailableVersions,
        RequiredVersions: RoslynCompiler.RequiredVersions,
        MissingVersions: compiler.MissingVersions,
        Net8SystemReferences: compiler.Net8SystemReferenceCount,
        Net48SystemReferences: compiler.Net48SystemReferenceCount,
        FailedReferences: failed);
}

// This service advertises one compiler spanning every supported Revit year.
// Starting with a partial reference matrix would make a nominal six-version
// gate silently exercise only the locally provisioned subset.  Refuse before
// binding the HTTP socket; /ready remains a defence-in-depth deployment gate.
var startupHealth = BuildHealthResponse();
if (startupHealth.Status != "ready")
{
    throw new InvalidOperationException(
        "Compile service startup refused: incomplete reference matrix; " +
        $"missing Revit versions=[{string.Join(", ", startupHealth.MissingVersions)}], " +
        $"net8 refs={startupHealth.Net8SystemReferences}, " +
        $"net48 refs={startupHealth.Net48SystemReferences}, " +
        $"failed refs={startupHealth.FailedReferences.Count}");
}

app.MapPost("/compile", (CompileRequest request) =>
{
    if (string.IsNullOrWhiteSpace(request.Code))
        return Results.BadRequest(new { error = "code is required" });

    if (string.IsNullOrWhiteSpace(request.RevitVersion))
        return Results.BadRequest(new { error = "revitVersion is required" });

    var result = compiler.Compile(request.Code, request.RevitVersion);

    return Results.Ok(new CompileResponse(result.Success, result.Errors));
});

app.MapGet("/health", () =>
{
    // Backward-compatible liveness endpoint: always 200, but never claims
    // "ready" when a supported Revit API or a framework reference set is absent.
    return Results.Ok(BuildHealthResponse());
});

app.MapGet("/ready", () =>
{
    // Deployment/readiness endpoint: a service that can compile only a subset
    // of the advertised Revit versions must not receive production traffic.
    var health = BuildHealthResponse();
    return health.Status == "ready"
        ? Results.Ok(health)
        : Results.Json(health, statusCode: StatusCodes.Status503ServiceUnavailable);
});

app.Run();

record CompileRequest(string Code, string RevitVersion);
record CompileResponse(bool Success, List<CompileError> Errors);
record HealthResponse(
    string Status,
    IReadOnlyList<string> Versions,
    IReadOnlyList<string> RequiredVersions,
    IReadOnlyList<string> MissingVersions,
    int Net8SystemReferences,
    int Net48SystemReferences,
    List<FailedReferenceDto> FailedReferences);
record FailedReferenceDto(string Path, string Category, string Error, DateTime Timestamp);

/// <summary>Marker — keeps Program.cs partial class visible to integration tests.</summary>
public partial class Program { }
