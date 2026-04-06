# Orchestrated unified stream (normative supplement)

This document defines **merge and ordering** behavior for the unified synthetic NDJSON stream feature. **Event field shapes** for v2-style match-related events and v3 `retail_purchase` events remain defined in their respective interchange contracts; this document does not redefine those payloads.

## Ordering

1. Each emitted line is one JSON object with a **synthetic timestamp** field per the relevant existing contract for that event type.
2. The **emit order** MUST be **non-decreasing** in the following **sort key** tuple (lexicographic comparison):
   - **K1**: Synthetic timestamp instant (UTC comparison per contract field semantics).
   - **K2**: `event` string (NDJSON field name), **ascending lexicographic** (ASCII order places `merch_purchase` before `retail_purchase` before `ticket_scan`).
   - **K3**: UTF-8 **lexicographic** order of the **exact JSON text** of the line as emitted, using the same **stable NDJSON line encoding** as the rest of this repository (sorted object keys, minimal separators, UTF-8, no ASCII escaping of non-ASCII where that is the established convention).

This yields a **total order** and **deterministic** merge when both sources are deterministic.

## Determinism

- Given **fixed** inputs (calendar content, retail parameters, randomness **seed**), two successful runs MUST produce **byte-identical** NDJSON output, including **identical per-line JSON encoding** as specified above for **K3**.

## Encoding

- **UTF-8** text, **one JSON object per line**, **newline** (`\n`) line endings for the stream; no byte-order mark.

## Mixed interchange file (v2 + v3 lines)

A single output file or stdout stream from **`stream`** MAY contain **multiple** `event` values interleaved in **emit order** (per **Ordering** above). **Each line** MUST still be a valid JSON object under the **existing normative contract** that governs that event (v2 interchange for match-style types, v3 interchange for `retail_purchase`). This supplement **does not** define a new global schema version or a merged super-schema; consumers validate line-by-line against the appropriate contract using the `event` field (and any version field those contracts specify).
