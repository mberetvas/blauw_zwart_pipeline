# Orchestrated stream — Feature 006 note

**Reference**: [`specs/004-unified-synthetic-stream/contracts/orchestrated-stream.md`](../../004-unified-synthetic-stream/contracts/orchestrated-stream.md)

Feature **006** does **not** change:

- **K1** synthetic timestamp ordering,
- **K2** `event` lexicographic tie-break,
- **K3** stable UTF-8 line encoding,

beyond what is already required to emit **valid** v2/v3 lines. Any new v2 **`match_id`** suffixing for season cycles MUST preserve **K3** stability (deterministic `match_id` strings).
