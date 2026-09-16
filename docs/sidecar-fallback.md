# Sidecar fallback — HTTP localhost

Primary transport is JSON-RPC over stdin/stdout via `tauri-plugin-shell` spawning the venv python
resolved by `core/config.py:get_venv_python()`:

- Windows: `venv/Scripts/python.exe`
- macOS/Linux: `venv/bin/python`

Rust handler `python_sidecar_call` forwards `{"id","method","params"}` line-delimited JSON
to the sidecar and returns the response. Spike requirement: `{"type":"hello"}` or
`{"method":"ping"}` round-trips in <2s.

## When spawn fails

If `tao::shell::spawn` fails, Rust logs:

```
sidecar failed: <venvPath>
```

and returns an error to the frontend. The GUI must:

- Keep the app open (no crash)
- Show a warning toast `t('toast.sidecarFailed')` with the venv path
- Continue in degraded mode (Find/ChapterList remain mocks in 1.1)

## Fallback: HTTP localhost

If the 10-minute stdin/stdout spike test cannot be stabilized (e.g., bundling `venv` binary vs `python -m`),
fallback is a tiny localhost HTTP server on `http://localhost:17381`:

```ts
// frontend
await fetch("http://localhost:17381/rpc", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ id, method, params }),
});
```

Python sidecar alternative entry:

```bash
venv/Scripts/python.exe -m core.config --http 17381
# or
venv/Scripts/python.exe -m http.server 17381  # mock
```

`core/config.py:handle_rpc` is transport-agnostic — same `{"id","method","params"}` shape
for both transports. The fallback doc path must exist at `docs/sidecar-fallback.md`
and the frontend `src/lib/sidecar.ts:callSidecar` must attempt HTTP after shell error.

## Sequential fetch only

No parallel scrape even when fallback is active (AD-3). All chapter fetches remain
sequential with 3–5s + jitter (10s safe) via `core/fetch.py` (Epic 2).

## Verification (spike)

```bash
# Tauri spawns venv python and ping round-trips
venv/Scripts/python.exe -c "import core.config, json; print(core.config.handle_rpc({'id':'1','method':'ping'}))"
# expected: {"id":"1","result":"pong"}
```

If this prints `pong`, the primary transport is working and fallback is doc-only.
