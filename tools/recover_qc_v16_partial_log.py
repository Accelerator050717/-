"""Recover only complete JSON fields from the observed truncated v16 log.

This never invents missing bytes. Streaming decompression of an incomplete
LZMA stream does NOT verify its final checksum or the full payload SHA256.
"""
import argparse
import base64
import hashlib
import json
import lzma
from pathlib import Path
import re


def complete_fields(text):
    decoder = json.JSONDecoder()
    if not text.startswith("{"):
        raise ValueError("Expected JSON object prefix")
    result, cursor = {}, 1
    while cursor < len(text):
        try:
            while cursor < len(text) and text[cursor] in " ,\n\r\t":
                cursor += 1
            key, end = decoder.raw_decode(text, cursor)
            if not isinstance(key, str) or key in result:
                raise ValueError("Unexpected or duplicate key")
            cursor = end
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text) or text[cursor] != ":":
                break
            cursor += 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            value, end = decoder.raw_decode(text, cursor)
            after = end
            while after < len(text) and text[after].isspace():
                after += 1
            # A numeric prefix before EOF must not become a complete value.
            if after == len(text) or text[after] not in ",}":
                break
            result[key] = value
            cursor = after
            if text[after] == "}":
                break
        except (ValueError, IndexError):
            break
    return result, cursor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    observed = args.input.read_bytes()
    text = observed.decode("utf-8")
    expected_hash = re.search(r'"sha256":"([0-9a-f]{64})"', text).group(1)
    expected_bytes = int(re.search(r'"bytes":(\d+)', text).group(1))
    encoded = re.search(r'"data":"([A-Za-z0-9+/=]+)', text).group(1)
    usable = encoded[:len(encoded) // 4 * 4]
    compressed = base64.b64decode(usable, validate=True)
    decoder = lzma.LZMADecompressor()
    raw = decoder.decompress(compressed, max_length=expected_bytes + 1)
    decoded_text = raw.decode("utf-8")
    fields, stopped_at = complete_fields(decoded_text)
    recovered_hash = hashlib.sha256(raw).hexdigest()
    full = decoder.eof and len(raw) == expected_bytes and recovered_hash == expected_hash
    metadata = {
        "schema": "v16-partial-log-recovery-1", "original_log_path": str(args.input),
        "original_log_bytes": len(observed), "original_log_sha256": hashlib.sha256(observed).hexdigest(),
        "base64_characters_observed": len(encoded), "base64_characters_used": len(usable),
        "compressed_bytes_available": len(compressed), "decoded_bytes_available": len(raw),
        "expected_full_payload_bytes": expected_bytes, "expected_full_payload_sha256": expected_hash,
        "recovered_prefix_sha256": recovered_hash, "lzma_end_of_stream": decoder.eof,
        "full_payload_integrity_verified": full, "complete_top_level_fields": list(fields),
        "complete_field_counts": {k: len(v) for k, v in fields.items() if isinstance(v, (list, dict))},
        "parser_stopped_at": stopped_at,
        "boundary": "Only syntactically complete observed JSON values; missing fields are not inferred. Without LZMA EOF/full SHA the recovered prefix has unverified end-to-end transport integrity.",
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "DIAGNOSTIC_PARTIAL_JSON.txt").write_bytes(raw)
    (args.out / "DIAGNOSTIC_RECOVERED_FIELDS.json").write_text(json.dumps(fields, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "DIAGNOSTIC_RECOVERY_CHECK.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
