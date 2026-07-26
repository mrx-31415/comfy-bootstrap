# comfy-bootstrap

Download the files required by a ComfyUI workflow and put them in the right
directories. ComfyUI itself must already be installed.

Asset and workflow management has no dependencies beyond Python 3.9 or newer.
Optional custom-node support uses a pinned `comfy-cli` and requires Python
3.10 or newer.

## Quick start

```bash
git clone https://github.com/mrx-31415/comfy-bootstrap.git
cd comfy-bootstrap

./comfy-bootstrap asset add flux-dev \
  https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors \
  models/unet/flux1-dev.safetensors \
  --token-env HF_TOKEN

./comfy-bootstrap workflow add flux-dev workflows/flux-dev.json
./comfy-bootstrap workflow link flux-dev flux-dev

export COMFYUI_DIR=/workspace/ComfyUI
export HF_TOKEN=your_huggingface_token
./comfy-bootstrap sync flux-dev
```

Commit `comfy-bootstrap.json` and the files under `workflows/`. On a new
Vast.ai or other cloud instance, clone this repository, set any required token
environment variables, and run the final `sync` command.

## Custom nodes

Bootstrap the optional custom-node tooling into the same Python environment
that runs an existing ComfyUI installation:

```bash
export COMFYUI_DIR=/workspace/ComfyUI
./comfy-bootstrap setup
```

If ComfyUI uses a specific interpreter, select it explicitly:

```bash
./comfy-bootstrap setup --python /workspace/venv/bin/python
```

`setup` installs the pinned `comfy-cli` version and ComfyUI-Manager when
missing, verifies the existing ComfyUI workspace, and writes executable paths
to the gitignored `.comfy-bootstrap/state.json`. It does not install or update
ComfyUI.

Scan an imported workflow and commit the resulting dependency specification:

```bash
./comfy-bootstrap node scan my-flow
./comfy-bootstrap node show my-flow
git add workflows/my-flow.nodes.json comfy-bootstrap.json
```

Once a workflow has a node dependency specification, `sync` installs those
nodes before downloading assets. Use `--skip-nodes` when nodes are managed
separately. Interactive terminals show a progress bar with size and download
speed; interrupted `.part` files resume automatically.

Successful custom-node installs are cached by dependency-spec checksum.
`sync` also detects nodes installed before the cache existed. Use
`--force-nodes` to reinstall them explicitly.

## Import an existing workflow

Copy a workflow from ComfyUI into the repository:

```bash
./comfy-bootstrap workflow import my-flow \
  /workspace/ComfyUI/user/default/workflows/my-flow.json
```

When a workflow contains ComfyUI's embedded `properties.models` metadata,
the importer registers and links its exact model URLs automatically. Model
filenames without embedded URLs are listed as unresolved so they can be added
explicitly. Use `--replace` to re-import an existing workflow while retaining
its current asset links.

## Find assets on Hugging Face

Search repositories, then list the files in the selected repository:

```bash
./comfy-bootstrap hf search "flux dev"
./comfy-bootstrap hf files black-forest-labs/FLUX.1-dev "*.safetensors"
```

Search output includes the exact `hf files` follow-up command. For a guided
search that also adds the selected file:

```bash
./comfy-bootstrap hf search "flux dev" \
  --add \
  --workflow flux-dev \
  --to diffusion_models \
  --token-env HF_TOKEN
```

For scripts, add a known repository file directly:

```bash
./comfy-bootstrap hf add \
  black-forest-labs/FLUX.1-dev \
  flux1-dev.safetensors \
  --to diffusion_models \
  --token-env HF_TOKEN \
  --workflow flux-dev
```

The asset name and destination filename are inferred from the selected file.
Override them with `--name` or `--filename`. Search finds repositories rather
than guessing a global filename match, so the final file selection remains
explicit.

## Manifest

The commands maintain a single JSON file:

```json
{
  "assets": {
    "flux-dev": {
      "path": "models/unet/flux1-dev.safetensors",
      "sha256": "optional 64-character checksum",
      "token_env": "HF_TOKEN",
      "url": "https://huggingface.co/.../flux1-dev.safetensors"
    }
  },
  "workflows": {
    "flux-dev": {
      "assets": ["flux-dev"],
      "file": "workflows/flux-dev.json",
      "node_dependencies": "workflows/flux-dev.nodes.json"
    }
  }
}
```

Paths are relative to the ComfyUI directory. Assets can be shared by several
workflows. Store the environment variable name in the manifest, never the
token itself. A SHA-256 checksum is optional but recommended, especially for
gated model downloads.

## Commands

```text
comfy-bootstrap asset add NAME URL PATH [--sha256 HASH] [--token-env ENV]
comfy-bootstrap asset remove NAME [--force]

comfy-bootstrap workflow add NAME FILE
comfy-bootstrap workflow import NAME FILE
comfy-bootstrap workflow remove NAME
comfy-bootstrap workflow link WORKFLOW ASSET [ASSET ...]
comfy-bootstrap workflow unlink WORKFLOW ASSET [ASSET ...]

comfy-bootstrap setup [--comfyui-dir PATH] [--python PATH]
comfy-bootstrap node scan WORKFLOW [--comfyui-dir PATH]
comfy-bootstrap node show WORKFLOW

comfy-bootstrap hf search QUERY [--limit N]
comfy-bootstrap hf search QUERY --add --workflow WORKFLOW --to DIRECTORY
comfy-bootstrap hf files REPO [PATTERN]
comfy-bootstrap hf add REPO FILE --to DIRECTORY --workflow WORKFLOW
comfy-bootstrap list
comfy-bootstrap show [NAME]
comfy-bootstrap sync WORKFLOW [--comfyui-dir PATH] [--skip-nodes]
```

Use `--replace` with `asset add` or `workflow add` to update an existing
entry. Use the global `--manifest PATH` option before the command to work with
a different manifest.

`sync` installs committed custom-node dependencies, skips completed files,
resumes `.part` downloads when the server supports HTTP ranges, retries
transient failures, and verifies configured checksums. It installs the
workflow under `user/default/workflows` only after all dependencies and assets
succeed. Override that location with `--workflow-dir`.

Guessing model URLs for filenames without embedded metadata remains
intentionally out of scope.
