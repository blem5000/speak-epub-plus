# Releasing Speak EPUB

Everything the release pipeline does, and the two traps that cost a release
each. The app is a Tauri desktop app; the Python backend is a separate
"runtime tier" that the app downloads once.

## What a release contains

| asset | size | when the user gets it |
|---|---|---|
| `Speak.EPUB_<v>_x64-setup.exe` / `.msi` | ~4–6 MB | installed app (**app tier**) |
| `Speak-EPUB-<v>-x64-portable.zip` | ~6 MB | portable build (app tier) |
| `speak-epub-runtime-<hash>.zip` | ~41 MB | downloaded **once** on the first launch, cached in `%LOCALAPPDATA%\speak-epub\runtime\<hash>` |
| `speak-epub-local-<hash>.zip` | ~60 MB | optional: only when the user turns on the local (Piper) engine |
| `latest.json` + `*.sig` | tiny | the signed update manifest |

The runtime tier's cache key comes from `scripts/runtime_descriptor.py`:
the pinned interpreter build + the digest of the **core** dependencies. An
app update therefore transfers only the app tier; the runtime is re-downloaded
only when the dependencies really changed.

## Procedure

1. Bump the version in **five** places: `package.json`, `package-lock.json`
   (two spots), `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`,
   `src-tauri/Cargo.lock`.
   Edit them with a text editor, never with PowerShell `Set-Content` — it
   writes a UTF-8 BOM (npm then fails) and `-Encoding ASCII` eats the
   em-dashes. Verify: no `EF BB BF` at the file start, `JSON.parse` succeeds.
2. Commit, tag and push:
   ```powershell
   git commit -m "chore: release vX.Y.Z"
   git tag vX.Y.Z
   git push origin main
   git push origin vX.Y.Z
   ```
3. Watch the CI: `gh run watch <run-id>`. The workflow builds the Python
   tiers, trims the runtime, packs the app tier and publishes the assets.
4. Publish the draft release: `gh release edit vX.Y.Z --draft=false
   --notes-file <notes.md>`.
5. Verify the assets (`gh release view vX.Y.Z --json assets`) — the release
   must carry `latest.json` and the tier assets.

## The two traps

- **`bundle.createUpdaterArtifacts: true`** (`src-tauri/tauri.conf.json`).
  Without it the Tauri CLI builds only the MSI and the NSIS installer, never
  the signed updater artifact, and the action ends with
  *"Signature not found for the updater JSON"* — no `latest.json`, no
  automatic updates.
- **`"updater:default"` in `src-tauri/capabilities/default.json`.**
  Tauri v2 blocks plugin commands by default, so the update check dies with
  *"Command plugin:updater|check not allowed by ACL"*.

Also: the action input is `uploadUpdaterJson` (`includeUpdaterJson` is the
v0 name), the updater endpoint must be `https://` (the plugin refuses plain
HTTP) and the NPM and Cargo versions of `tauri-plugin-updater` must match.

## The signing key

- The **private key** lives only in the GitHub secret
  `TAURI_SIGNING_PRIVATE_KEY` (no password) and in a local backup OUTSIDE
  the repository — e.g. `%USERPROFILE%\.speak-epub\tauri-signing\`.
  **Without it no further release can be signed** (the manifest, and with it
  every automatic update, stops working).
- The **public key** is in `src-tauri/tauri.conf.json` (`plugins.updater.pubkey`)
  and in the repo — that one is public by design.
- Rotating the key means: generate a new pair, update the secret, update the
  `pubkey` in `tauri.conf.json` and ship a release. Existing installs only
  accept updates signed with the key they were built with, so the rotation
  release must be installed manually once.

## Local smoke test of a release

Never trust a local build alone — a release is only as good as the artefact
that users download:

```powershell
gh release download vX.Y.Z --pattern "*-portable.zip" --dir $tmp
# unzip, run speak-epub.exe, then check:
Get-Content "$env:LOCALAPPDATA\speak-epub\app.log"
```

The log records the runtime tier that was used and the result of the signed
update check.
