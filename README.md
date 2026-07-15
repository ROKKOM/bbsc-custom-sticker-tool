# Sticker Outline Service

Upload an image, get back:
- a background-removed PNG cutout
- a die-cut style SVG contour outline (offset border), ready for sticker printers / cutting plotters

## How it works

1. **rembg** (`isnet-general-use` model) removes the background → clean alpha mask
2. **OpenCV** dilates the alpha mask outward by `offset_px` — this is the border gap around the artwork
3. The dilated mask is written to a PBM bitmap
4. **potrace** traces the bitmap into a smooth SVG path
5. Both the PNG cutout and the SVG outline are returned as JSON (base64 PNG + raw SVG string)

## Run locally

```bash
docker build -t sticker-outline-service .
docker run -p 8000:8000 sticker-outline-service
```

Then visit `http://localhost:8000` for a basic upload form, or:

```bash
curl -X POST "http://localhost:8000/sticker?offset_px=12" \
  -F "file=@/path/to/your/image.png" \
  | jq
```

For a quick visual check in the browser (renders cutout + outline overlaid):

```
POST http://localhost:8000/sticker/preview
```

## API

### `POST /sticker`

**Form field:** `file` — the image to process

**Query params:**
| param | default | description |
|---|---|---|
| `offset_px` | 12 | gap between artwork and cut line, in pixels |
| `turdsize` | 10 | potrace: suppress speckles smaller than this |
| `alphamax` | 1.0 | potrace: corner smoothing (0 = sharp corners, ~1.3 = very round) |

**Response:**
```json
{
  "cutout_png_base64": "...",
  "outline_svg": "<svg ...>...</svg>",
  "width": 1024,
  "height": 1024,
  "offset_px": 12
}
```

### `GET /health`
Basic healthcheck, returns `{"status": "ok"}` — useful for Magic Containers health checks.

## Deploying to Bunny Magic Containers

Magic Containers deploys from an image in a container registry (Docker Hub or GitHub Container Registry) — it doesn't build from source directly, so the image needs to exist in a registry first. You have two ways to get it there — pick whichever means you don't need Docker installed locally.

### 1a. Build the image online with GitHub Actions (no local Docker needed)

This repo includes `.github/workflows/docker-build.yml`, which builds the image on GitHub's servers and pushes it to GitHub Container Registry (`ghcr.io`) automatically on every push to `main`.

1. Push this project to a new GitHub repo
2. The workflow runs automatically — check the **Actions** tab to watch the build
3. Once it finishes, your image is live at `ghcr.io/YOUR_GH_USERNAME/sticker-outline-service:latest`
4. In your repo's **Settings → Packages**, make sure the package visibility is set appropriately (private packages need a token with `read:packages` when you connect it to Bunny)

That's it — nothing to build or push from your own machine.

### 1b. Build and push locally (if you'd rather)

```bash
docker build --platform linux/amd64 -t YOUR_DOCKERHUB_USERNAME/sticker-outline-service:latest .
docker push YOUR_DOCKERHUB_USERNAME/sticker-outline-service:latest
```

> Note: Magic Containers only supports `linux/amd64` images. If you're building on Apple Silicon, the `--platform linux/amd64` flag above is required.

### 2. Connect your registry

In the bunny.net dashboard: **Magic Containers → Image Registries → Add Image Registry**, and provide a read-only personal access token for Docker Hub or GitHub.

### 3. Deploy the app

- **Magic Containers → Add App**
- Choose **Single region deployment** to start (simplest — this is a stateless processing service, not something that needs to be geo-distributed across 40+ regions unless you're serving a global user base at scale)
- **Add Container** → select your registry, image, and tag
- Under **Endpoints**, add a new endpoint exposing container port `8000` (CDN or Anycast, your call)
- Confirm and deploy

Once deployed, your endpoint URL will serve this API directly — point your upload form's fetch/axios call at `https://your-endpoint.b-cdn.net/sticker`.

### Notes on cost/sizing

- The image is somewhat heavy due to `onnxruntime` + the baked-in model (~150–250MB extra). If startup size matters, consider trimming to a smaller rembg model (`u2netp` is much lighter than `isnet-general-use`, at some quality cost).
- CPU is billed per second and RAM in 64MB increments per hour on Magic Containers — this service is CPU-bound during inference, so keep an eye on actual usage vs. allocated resources once you have real traffic.

## Tuning tips

- **`offset_px`** controls how far the cut line sits from the artwork edge — most commercial sticker printers default to somewhere around 2–5mm, which depending on your image DPI is roughly 8–20px.
- If outlines come out jagged, raise `alphamax` (smoother corners) or increase `turdsize` (removes small stray specks from noisy alpha masks).
- If fine details (thin lines, small gaps) are getting lost, lower `offset_px` and/or preprocess the source image at higher resolution before upload — the dilation/tracing quality scales with pixel resolution.
