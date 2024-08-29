# Use the official Python image as a base image
FROM python:3.10-slim-buster

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    build-essential \
    ffmpeg  # Add ffmpeg to the list of installed packages

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the project
COPY . /app/

# Expose the port for Uvicorn
EXPOSE 8000

# Start the Uvicorn server
# CMD ["uvicorn", "youtube_downloader.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
CMD ["daphne", "-u", "/tmp/daphne.sock", "youtube_downloader.asgi:application", "--bind", "0.0.0.0", "--port", "8000"]
