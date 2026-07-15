FROM python:3.11-slim

# potrace: bitmap-to-SVG tracer
# libgl1 / libglib2.0-0: runtime libs some opencv wheels expect
RUN apt-get update && apt-get install -y --no-install-recommends \
        potrace \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Bake the rembg model into the image at build time so the first request
# isn't slowed down by a model download.
RUN python -c "from rembg import new_session; new_session('isnet-general-use')"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
