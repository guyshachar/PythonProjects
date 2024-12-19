# Use an official Python runtime as a base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 
    # Prevent Python from writing pyc files
ENV PYTHONUNBUFFERED=1        
    # Ensure logs are output immediately 

    # Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Expose application port (if applicable)
EXPOSE 8000

# Set the default command to run the application
CMD ["python", "src/main.py"]
