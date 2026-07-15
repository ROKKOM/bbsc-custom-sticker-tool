"""
Sticker Outline Service
------------------------
Upload an image -> get back:
  - a transparent PNG cutout (background removed)
  - a die-cut style SVG contour outline (offset around the artwork), ready
    for sticker printers / cutting plotters.

Pipeline:
  1. rembg removes the background -> RGBA image with alpha mask
  2. OpenCV dilates the alpha mask outward by `offset_px` (the sticker border gap)
  3. The dilated mask is written out as a PBM bitmap
  4. potrace (CLI) traces the bitmap into a smooth SVG path
  5. Both the cutout PNG and the outline SVG are returned as base64 JSON
     (plus a combined preview endpoint for quick visual testing)
"""

import base64
import io
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from PIL import Image
from rembg import remove, new_session

app = FastAPI(
    title="Sticker Outline Service",
    description="Background removal + die-cut contour SVG generation for sticker printing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at startup, reused across requests (much faster than per-request loads)
_SESSION = new_session("isnet-general-use")


def _remove_background(image_bytes: bytes) -> Image.Image:
    """Run rembg and return an RGBA PIL image with a clean alpha mask."""
    result = remove(image_bytes, session=_SESSION)
    return Image.open(io.BytesIO(result)).convert("RGBA")


def _dilate_alpha_mask(rgba: Image.Image, offset_px: int, alpha_threshold: int = 20) -> np.ndarray:
    """Threshold the alpha channel to binary, then dilate it outward by offset_px.

    Returns a uint8 numpy array (0 / 255) the same size as the source image.
    """
    alpha = np.array(rgba.split()[-1])
    binary = np.where(alpha > alpha_threshold, 255, 0).astype(np.uint8)

    if offset_px > 0:
        kernel_size = offset_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        binary = cv2.dilate(binary, kernel, iterations=1)

    return binary


def _mask_to_svg(mask: np.ndarray, turdsize: int = 10, alphamax: float = 1.0, opttolerance: float = 0.2) -> str:
    """Write mask to a PBM bitmap and trace it with potrace into an SVG string."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pbm_path = tmp_path / "mask.pbm"
        svg_path = tmp_path / "mask.svg"

        # potrace traces BLACK pixels as foreground, so invert: shape = black (0)
        Image.fromarray(255 - mask).convert("1").save(pbm_path, format="PPM")

        cmd = [
            "potrace",
            str(pbm_path),
            "-s",  # SVG output
            "-o", str(svg_path),
            "-t", str(turdsize),
            "-a", str(alphamax),
            "-O", str(opttolerance),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"potrace failed: {proc.stderr}")

        return svg_path.read_text()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <html>
      <body style="font-family: sans-serif; max-width: 640px; margin: 40px auto;">
        <h2>Sticker Outline Service</h2>
        <p>POST an image to <code>/sticker</code> (multipart form field: <code>file</code>)
        to get back a background-removed PNG and a die-cut SVG outline.</p>
        <form action="/sticker" method="post" enctype="multipart/form-data">
          <input type="file" name="file" accept="image/*" required />
          <button type="submit">Generate</button>
        </form>
        <p style="color:#666; font-size: 0.9em;">
          For a quick visual test, use <code>/sticker/preview</code> instead — it returns
          an SVG image directly (cutout + outline) that renders in the browser.
        </p>
      </body>
    </html>
    """


@app.post("/sticker")
async def generate_sticker(
    file: UploadFile = File(...),
    offset_px: int = Query(12, ge=0, le=100, description="Border gap between artwork and cut line, in pixels"),
    turdsize: int = Query(10, ge=0, description="potrace: suppress speckles smaller than this"),
    alphamax: float = Query(1.0, ge=0.0, le=1.3341, description="potrace: corner smoothing"),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file")

    image_bytes = await file.read()

    try:
        cutout = _remove_background(image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {exc}")

    mask = _dilate_alpha_mask(cutout, offset_px=offset_px)
    svg = _mask_to_svg(mask, turdsize=turdsize, alphamax=alphamax)

    png_buffer = io.BytesIO()
    cutout.save(png_buffer, format="PNG")
    png_b64 = base64.b64encode(png_buffer.getvalue()).decode("ascii")

    return {
        "cutout_png_base64": png_b64,
        "outline_svg": svg,
        "width": cutout.width,
        "height": cutout.height,
        "offset_px": offset_px,
    }


@app.post("/sticker/preview", response_class=HTMLResponse)
async def preview_sticker(
    file: UploadFile = File(...),
    offset_px: int = Query(12, ge=0, le=100),
):
    """Quick visual check: renders the cutout PNG layered over the traced outline."""
    result = await generate_sticker(file=file, offset_px=offset_px)
    return f"""
    <html>
      <body style="background:#e5e5e5; display:flex; align-items:center; justify-content:center; height:100vh; margin:0;">
        <div style="position:relative; width:{result['width']}px; height:{result['height']}px;">
          <div style="position:absolute; inset:0;">{result['outline_svg']}</div>
          <img src="data:image/png;base64,{result['cutout_png_base64']}"
               style="position:absolute; inset:0; width:100%; height:100%;" />
        </div>
      </body>
    </html>
    """


@app.get("/health")
def health():
    return {"status": "ok"}
