# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libpq-dev \
    binutils \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*
# Install dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project
COPY . .

# Collect static files (optional if using static files)
RUN python manage.py collectstatic --noinput

# Expose port
EXPOSE 8000

# Start the Django app using gunicorn
CMD ["python","-m","gunicorn", "dormwatch.wsgi:application", "--bind", "0.0.0.0:80"]

