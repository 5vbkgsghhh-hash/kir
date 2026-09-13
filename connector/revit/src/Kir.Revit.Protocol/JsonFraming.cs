using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Kir.Revit.Protocol
{
    public static class JsonFraming
    {
        public static readonly JsonSerializerOptions Options = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = false,
            PropertyNamingPolicy = null,
            WriteIndented = false,
        };

        public sealed class PreparedCompilerRequest
        {
            private readonly byte[] _payload;
            private readonly byte[] _header;
            public int PayloadLength => _payload.Length;
            internal PreparedCompilerRequest(byte[] payload) { _payload = payload; _header = LengthBytes(payload.Length); }
            public async Task WriteAsync(Stream stream, CancellationToken cancellationToken)
            {
                if (stream == null) throw new ArgumentNullException(nameof(stream));
                await stream.WriteAsync(_header, 0, _header.Length, cancellationToken).ConfigureAwait(false);
                await stream.WriteAsync(_payload, 0, _payload.Length, cancellationToken).ConfigureAwait(false);
                await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
        }

        // Own the complete encoded frame before a compiler process is started.
        // Callers cannot mutate its bytes or the source/reference snapshot.
        public static PreparedCompilerRequest PrepareCompilerRequest(CompilerRequest request)
        {
            if (request == null) throw new InvalidDataException("compiler_request_invalid: null request");
            var snapshot = new CompilerRequest
            {
                Protocol = request.Protocol, Source = request.Source,
                ReferencePaths = request.ReferencePaths == null ? null! : new List<string>(request.ReferencePaths),
            };
            ValidateCompilerRequest(snapshot);
            var payload = JsonSerializer.SerializeToUtf8Bytes(snapshot, Options);
            CheckCompilerPayload(payload);
            return new PreparedCompilerRequest(payload);
        }

        public static CompilerRequest ReadCompilerRequest(Stream stream)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            var length = DecodeLength(ReadExact(stream, 4), ProtocolConstants.MaxCompilerRequestFrameBytes);
            var payload = ReadExact(stream, length);
            CheckCompilerPayload(payload);
            var request = JsonSerializer.Deserialize<CompilerRequest>(payload, Options)
                ?? throw new InvalidDataException("compiler_request_invalid: null request");
            ValidateCompilerRequest(request);
            return request;
        }

        private static void ValidateCompilerRequest(CompilerRequest request)
        {
            if (request == null || request.Protocol != ProtocolConstants.Version)
                throw new InvalidDataException("compiler_request_invalid: missing request or protocol mismatch");
            if (string.IsNullOrWhiteSpace(request.Source) || request.Source.Length > ProtocolConstants.MaxSourceChars)
                throw new InvalidDataException("compiler_source_limit: nonempty source must fit 6 Mi UTF-16 units");
            CheckUnicode(request.Source, "compiler_source_encoding");
            if (request.ReferencePaths == null || request.ReferencePaths.Count > ProtocolConstants.MaxCompilerReferencePaths)
                throw new InvalidDataException("compiler_reference_limit: too many or missing reference paths");
            foreach (var path in request.ReferencePaths)
            {
                if (string.IsNullOrWhiteSpace(path) || path.Length > ProtocolConstants.MaxCompilerReferencePathChars)
                    throw new InvalidDataException("compiler_reference_limit: invalid reference path length");
                CheckUnicode(path, "compiler_reference_encoding");
            }
            if (JsonSerializer.SerializeToUtf8Bytes(request.ReferencePaths, Options).Length > ProtocolConstants.MaxCompilerReferenceJsonBytes)
                throw new InvalidDataException("compiler_reference_limit: serialized reference paths exceed 1 MiB");
        }

        private static void CheckUnicode(string value, string code)
        {
            try { new UTF8Encoding(false, true).GetByteCount(value); }
            catch (EncoderFallbackException) { throw new InvalidDataException(code + ": unpaired UTF-16 surrogate"); }
        }

        private static void CheckCompilerPayload(byte[] payload)
        {
            if (payload.Length > ProtocolConstants.MaxCompilerRequestFrameBytes)
                throw new InvalidDataException("compiler_request_limit: encoded internal frame is too large");
            using (var document = StrictJson.Parse(payload))
            {
                var root = document.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                    throw new InvalidDataException("compiler_request_invalid: expected an object");
                var fields = 0;
                foreach (var property in root.EnumerateObject())
                {
                    if (property.Name != "protocol" && property.Name != "source" && property.Name != "reference_paths")
                        throw new InvalidDataException("compiler_request_invalid: unknown envelope field");
                    fields++;
                }
                if (fields != 3 || !root.TryGetProperty("source", out var source) || source.ValueKind != JsonValueKind.String
                    || !root.TryGetProperty("reference_paths", out var references) || references.ValueKind != JsonValueKind.Array)
                    throw new InvalidDataException("compiler_request_invalid: incomplete envelope");
                var sourceBytes = Encoding.UTF8.GetByteCount(source.GetRawText());
                var referenceBytes = Encoding.UTF8.GetByteCount(references.GetRawText());
                if (referenceBytes > ProtocolConstants.MaxCompilerReferenceJsonBytes)
                    throw new InvalidDataException("compiler_reference_limit: serialized reference paths exceed 1 MiB");
                if (payload.Length - sourceBytes - referenceBytes > ProtocolConstants.MaxCompilerEnvelopeBytes)
                    throw new InvalidDataException("compiler_request_limit: fixed envelope exceeds 4 KiB");
            }
        }

        public static void Write<T>(Stream stream, T value)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            var payload = Encode(value);
            var length = LengthBytes(payload.Length);
            stream.Write(length, 0, length.Length);
            stream.Write(payload, 0, payload.Length);
            stream.Flush();
        }

        public static async Task WriteAsync<T>(Stream stream, T value, CancellationToken cancellationToken)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            cancellationToken.ThrowIfCancellationRequested();
            var payload = Encode(value);
            var length = LengthBytes(payload.Length);
            await stream.WriteAsync(length, 0, length.Length, cancellationToken).ConfigureAwait(false);
            await stream.WriteAsync(payload, 0, payload.Length, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        private static byte[] Encode<T>(T value)
        {
            byte[] payload;
            if (value is ConnectorRequest request && request.Kind == RequestKinds.CancelBeforeStart)
            {
                // The new binding-only command has an exact wire shape. Keep
                // historical DTO serialization unchanged for every other kind;
                // global null omission would lose precondition null semantics.
                if (request.Source != null || request.RecoveryTarget != null || request.Precondition == null)
                    throw new InvalidDataException("cancel requires a source-free complete binding");
                payload = JsonSerializer.SerializeToUtf8Bytes(new Dictionary<string, object?>
                {
                    ["protocol"] = request.Protocol, ["request_id"] = request.RequestId,
                    ["target"] = request.Target, ["session_id"] = request.SessionId,
                    ["token"] = request.Token, ["kind"] = request.Kind, ["timeout_ms"] = request.TimeoutMs,
                    ["operation_id"] = request.OperationId, ["source_sha256"] = request.SourceSha256,
                    ["precondition"] = new Dictionary<string, object?>
                    {
                        ["document_key"] = request.Precondition.DocumentKey, ["revision"] = request.Precondition.Revision,
                        ["active_view_id"] = request.Precondition.ActiveViewId, ["selection_digest"] = request.Precondition.SelectionDigest,
                    },
                }, Options);
            }
            else payload = JsonSerializer.SerializeToUtf8Bytes(value, Options);
            if (payload.Length > ProtocolConstants.MaxFrameBytes)
                throw new InvalidDataException("JSON frame exceeds the protocol limit");
            return payload;
        }

        private static byte[] LengthBytes(int count)
        {
            var length = new byte[4];
            length[0] = (byte)count;
            length[1] = (byte)(count >> 8);
            length[2] = (byte)(count >> 16);
            length[3] = (byte)(count >> 24);
            return length;
        }

        public static T Read<T>(Stream stream)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            var length = DecodeLength(ReadExact(stream, 4));
            return Decode<T>(ReadExact(stream, length));
        }

        public static async Task<T> ReadAsync<T>(Stream stream, CancellationToken cancellationToken)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            var length = DecodeLength(await ReadExactAsync(stream, 4, cancellationToken).ConfigureAwait(false));
            return Decode<T>(await ReadExactAsync(stream, length, cancellationToken).ConfigureAwait(false));
        }

        // Raw external frames preserve a caller's already-encoded UTF-8 bytes.
        // These are NOT the expanded internal compiler-request profile.
        public static async Task WriteRawAsync(Stream stream, byte[] payload, CancellationToken cancellationToken)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            if (payload == null) throw new ArgumentNullException(nameof(payload));
            var detached = (byte[])payload.Clone();
            CheckRaw(detached);
            var length = LengthBytes(detached.Length);
            await stream.WriteAsync(length, 0, length.Length, cancellationToken).ConfigureAwait(false);
            await stream.WriteAsync(detached, 0, detached.Length, cancellationToken).ConfigureAwait(false);
            await stream.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        public static async Task<byte[]> ReadRawAsync(Stream stream, CancellationToken cancellationToken)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            var length = DecodeLength(await ReadExactAsync(stream, 4, cancellationToken).ConfigureAwait(false));
            var payload = await ReadExactAsync(stream, length, cancellationToken).ConfigureAwait(false);
            CheckRaw(payload);
            return payload;
        }

        private static void CheckRaw(byte[] payload)
        {
            if (payload.Length == 0 || payload.Length > ProtocolConstants.MaxFrameBytes)
                throw new InvalidDataException("Invalid JSON frame length");
            using (StrictJson.Parse(payload)) { }
        }

        private static int DecodeLength(byte[] lengthBytes, int maximum = ProtocolConstants.MaxFrameBytes)
        {
            var length = lengthBytes[0]
                         | (lengthBytes[1] << 8)
                         | (lengthBytes[2] << 16)
                         | (lengthBytes[3] << 24);
            if (length <= 0 || length > maximum)
                throw new InvalidDataException("Invalid JSON frame length");
            return length;
        }

        private static T Decode<T>(byte[] payload)
        {
            using (var parsed = StrictJson.Parse(payload))
            {
                if (typeof(T) == typeof(ConnectorRequest))
                    RequestKinds.ValidateCancellationPayload(parsed.RootElement);
                return JsonSerializer.Deserialize<T>(payload, Options)
                       ?? throw new InvalidDataException("JSON frame contained null");
            }
        }

        private static async Task<byte[]> ReadExactAsync(Stream stream, int count, CancellationToken cancellationToken)
        {
            var buffer = new byte[count];
            var offset = 0;
            while (offset < count)
            {
                var read = await stream.ReadAsync(buffer, offset, count - offset, cancellationToken).ConfigureAwait(false);
                if (read <= 0) throw new EndOfStreamException("JSON frame ended early");
                offset += read;
            }
            return buffer;
        }

        private static byte[] ReadExact(Stream stream, int count)
        {
            var buffer = new byte[count];
            var offset = 0;
            while (offset < count)
            {
                var read = stream.Read(buffer, offset, count - offset);
                if (read <= 0) throw new EndOfStreamException("JSON frame ended early");
                offset += read;
            }
            return buffer;
        }
    }
}
