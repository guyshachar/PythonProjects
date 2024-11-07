# Use the official Python image from the Docker Hub
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the script into the container
#RUN mkdir -p /Shared
COPY refPortalAppLocal.py .

# Install any necessary dependencies (if needed)
RUN pip install playwright && playwright install && playwright install-deps 

# Command to run the script
CMD ["python", "refPortalAppLocal.py"]
