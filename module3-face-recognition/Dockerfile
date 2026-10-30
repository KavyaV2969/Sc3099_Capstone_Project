FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for OpenCV and face_recognition
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libopencv-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "from facenet_pytorch import InceptionResnetV1; InceptionResnetV1(pretrained='vggface2'); from uniface.spoofing import MiniFASNet, MiniFASNetWeights; MiniFASNet(model_name=MiniFASNetWeights.V2, providers=['CPUExecutionProvider'])"

# Copy application code
COPY . .

# Expose port
EXPOSE 8001


HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"
# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--timeout-keep-alive", "30"]
