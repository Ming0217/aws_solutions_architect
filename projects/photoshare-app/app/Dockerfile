# Minimal image for the PhotoShare API. Listens on 8000 (the infra contract).
FROM python:3.12-slim

# System deps kept minimal; slim image + no build tools needed for these wheels.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py db.py ./
COPY static ./static

EXPOSE 8000

# Single worker is fine for t3.micro; scale out via the ASG, not workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
