FROM python:3.11

WORKDIR /app

# 1) Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Copy your package folder
COPY strmgen/ ./strmgen/

# 4) Unbuffered logs
ENV PYTHONUNBUFFERED=1

# 5) Run from inside the package
WORKDIR /app/strmgen


# expose port for UI
EXPOSE 8000

# default to serve the UI
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]