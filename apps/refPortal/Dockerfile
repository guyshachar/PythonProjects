# Use the official Python image from the Docker Hub
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    curl \
    libglib2.0-0 \
    libnss3 \
    libx11-dev \
    libx11-6 \
    libxext6 \
    libxrandr2 \
    libxtst6 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libappindicator3-1 \
    libxss1 \
    libnspr4 \
    libnss3 \
    #libvpx6 \
    libxcomposite1 \
    libxdamage1 \
    && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browsers
RUN playwright install
RUN playwright install-deps    

# Copy the script into the container
#RUN mkdir -p /Shared
COPY . .

# Install any necessary dependencies (if needed)
#RUN pip install --upgrade pip
#RUN pip install playwright 
#RUN playwright install 
#RUN playwright install-deps 

# Command to run the script
CMD ["python", "refPortalAppLocal.py"]
