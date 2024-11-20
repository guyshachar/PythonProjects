# Use the official Python image from the Docker Hub
FROM python:3.13-slim

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

# Define entrypoint to start Tailscale and your app
# Start Tailscale and your Python script
ENV logLevel=INFO
ENV loadInterval=30000
ENV loadUrl=https://ref.football.org.il/login
ENV loadUrl2=https://www.google.com/
ENV refPortalSM=refPortal/referees2
# Command to run the script
#CMD ["python", "test.py"]
CMD ["python", "refPortalAppLocal.py"]
