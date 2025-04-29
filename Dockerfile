FROM python:3.12

# 1) system-level deps (if you need ffmpeg, git, etc, install here)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # e.g. git ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2) install python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) copy the code
COPY . .

# 4) expose your UI port
EXPOSE 8808

# 5) entrypoint
CMD ["uvicorn", "strmgen.main:app", "--host", "0.0.0.0", "--port", "8808"]