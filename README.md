YouTube Downloader with Django, Celery, PostgreSQL, Redis, and Docker
This project is a YouTube downloader application built using Django. It uses Celery for handling background tasks, PostgreSQL as the database, Redis as the message broker, and Docker for containerization. The application allows downloading YouTube videos with optional audio merging, using ffmpeg for the merging process.

Table of Contents
Project Structure
Setup and Installation
Prerequisites
Configuration
Running the Project
Services Overview
Django Application
Celery Worker
PostgreSQL Database
Redis Message Broker
FFmpeg for Video Merging
Usage
Starting a Download
Checking Status
Downloading the File
Development and Debugging
Troubleshooting
Project Structure
arduino
Copy code
youtube_downloader/
├── downloader/
│   ├── migrations/
│   ├── templates/
│   ├── static/
│   ├── views.py
│   ├── urls.py
│   ├── models.py
│   ├── tasks.py
│   └── ...
├── youtube_downloader/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── ...
├── manage.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
Setup and Installation
Prerequisites
Docker and Docker Compose installed on your machine.
A basic understanding of Docker, Django, and Celery.
Configuration
Update the settings.py:

Ensure environment variables are used for database and Redis settings.
Update CHANNEL_LAYERS, CELERY_BROKER_URL, and DATABASES to use environment variables.
Install Dependencies:

Ensure requirements.txt includes necessary packages such as Django, Celery, Redis, psycopg2, and ffmpeg.
Running the Project
Build and Start the Containers:

bash
Copy code
docker-compose up --build
Apply Database Migrations:

bash
Copy code
docker-compose exec web python manage.py migrate
Create a Superuser (Optional):

bash
Copy code
docker-compose exec web python manage.py createsuperuser
Access the Application:

The Django application will be accessible at http://127.0.0.1:8000.
Services Overview
Django Application
The main web application runs on http://127.0.0.1:8000.
Uvicorn is used as the ASGI server, enabling WebSocket support.
Celery Worker
Handles background tasks such as downloading and merging videos.
Uses Redis as the broker and result backend.
PostgreSQL Database
Stores task data, including download status, file paths, etc.
Automatically initialized with database name youtube_downloader_db, user rajat, and password secret.
Redis Message Broker
Acts as the broker for Celery and as the backend for Django Channels.
FFmpeg for Video Merging
ffmpeg is used for merging video and audio files.
Installed inside the Docker container as part of the Dockerfile.
Usage
Starting a Download
You can start a download using a cURL request or via the frontend.

Example cURL request:

bash
Copy code
curl -X POST 'http://127.0.0.1:8000/start_download/' \
  -H 'Content-Type: application/json' \
  -H 'X-CSRFToken: <csrf-token>' \
  --data-raw '{"url":"https://www.youtube.com/watch?v=KXItezz-BhA","resolution":"highest-available","include_audio":true}'
Checking Status
You can check the status of the download via WebSocket or API endpoints.

Downloading the File
Once the download is complete, a signed URL will be generated. You can use this URL to download the file directly.

Development and Debugging
Run Django Shell:

bash
Copy code
docker-compose exec web python manage.py shell
Debugging Celery:

Ensure psycopg2 is installed.
Check logs using docker-compose logs worker.
Accessing Containers:

Web: docker-compose exec web bash
Worker: docker-compose exec worker bash
Troubleshooting
Database Connection Issues:

Ensure PostgreSQL is up and running.
Verify environment variables are correctly set.
FFmpeg Not Found:

Ensure ffmpeg is installed in the Docker container by checking the Dockerfile.
ModuleNotFoundError:

Ensure all dependencies are listed in requirements.txt and the Docker image is rebuilt.
This README.md serves as a complete guide for understanding, running, and maintaining the YouTube downloader project, along with handling potential issues during development and deployment.