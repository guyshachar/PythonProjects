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
    telnet \
    ping \
    traceroute \
    && apt-get clean && \
    curl -fsSL https://tailscale.com/install.sh | sh

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

# Start the Tailscale daemon on container start
# Use the userspace networking mode since Koyeb does not allow privileged mode
RUN mkdir -p /var/run/tailscale /var/cache/tailscale

# Define entrypoint to start Tailscale and your app
# Start Tailscale and your Python script
ENV loadInterval=5000
ENV loadUrl=https://ref.football.org.il/login
ENV loadUrl2=https://www.google.com/
ENV refId=025092271
ENV refPortalId=43679
ENV refPortalPassword=S073XdLR
ENV TAILSCALE_AUTH_KEY=tskey-auth-kU4aJgfjBm11CNTRL-hG1N4RaQEb9xT47RQ8qga9gdAgX39urca
ENV HOSTNAME=KoyebDockerRefPortal
ENV TS_EXIT_NODE=100.104.124.186
ENTRYPOINT ["/bin/sh", "-c", "tailscaled --tun=userspace-networking & \
                             tailscale up --authkey=${TAILSCALE_AUTH_KEY} --hostname=${HOSTNAME} && \
                             tailscale set --exit-node=${TS_EXIT_NODE} --exit-node-allow-lan-access --accept-routes=true && \
                             python refPortalAppLocal.py"]
# Command to run the script
#CMD ["python", "test.py"]
#CMD ["python", "refPortalAppLocal.py"]
