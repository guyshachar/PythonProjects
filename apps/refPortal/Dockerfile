# Use the official Python image from the Docker Hub
FROM python:3.13-slim
VOLUME ["/run/referees"]
VOLUME ["/run/config"]

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
COPY *.py .
COPY config/* .

# Install any necessary dependencies (if needed)
#RUN pip install --upgrade pip
#RUN pip install playwright 
#RUN playwright install 
#RUN playwright install-deps 

# Define entrypoint to start Tailscale and your app
# Start Tailscale and your Python script
ENV BUILD_DATE=202412202144
ENV logLevel=INFO
ENV loadInterval=30000
ENV loadUrl=https://ref.football.org.il/login
ENV loadUrl2=https://www.google.com/
ENV refPortalSM=refPortal/referees2
ENV twilioSend=True
ENV alwaysClosePage=False
ENV mqttPublish=True
ENV concurrentPages=4

# Command to run the script
#CMD ["python", "test.py"]
CMD ["python", "refPortalApp.py"]