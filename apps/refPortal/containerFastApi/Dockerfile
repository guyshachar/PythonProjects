# Define custom function directory
ARG FUNCTION_DIR="/lambdaFunction"

# FROM mcr.microsoft.com/playwright/python:v1.31.0-focal as build-image
#FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy AS build-image
FROM mcr.microsoft.com/playwright/python:v1.51.0-noble@sha256:a7d74e5d10e9a25b9c95cec1d702bdaa83a616e9c57b0c3f08e384c223da95df AS build-image

# Install aws-lambda-cpp build dependencies
RUN apt-get update
#RUN apt-get install -y \
#  tzdata
RUN apt-get install -y \
  g++ \
  make \
  cmake \
  unzip \
  libcurl4-openssl-dev \
  software-properties-common \
  fonts-liberation \
  libappindicator3-1 \
  #libasound2 \
  libatk-bridge2.0-0 \
  libatk1.0-0 \
  libcups2 \
  libdbus-1-3 \
  libgdk-pixbuf2.0-0 \
  libnspr4 \
  libnss3 \
  libraqm-dev \
  pciutils \
  xdg-utils

# Include global arg in this stage of the build
ARG FUNCTION_DIR

# Copy function code
RUN mkdir -p ${FUNCTION_DIR}
COPY containerFastApi/. ${FUNCTION_DIR}

WORKDIR ${FUNCTION_DIR}

RUN mkdir -p /rpApi
COPY rpApi/*.py /rpApi/.

RUN mkdir -p /templates
COPY rpApi/*.py /rpApi/.

COPY shared/*.py /shared/.
COPY shared/db/ /shared/db/
COPY shared/messaging/ /shared/messaging/
COPY shared/orgRelated/ /shared/orgRelated/

# Install the function's dependencies
RUN pip install \
    --target ${FUNCTION_DIR} \
        awslambdaric
        
# Add requirements.txt and install dependencies
COPY containerFastApi/requirements.txt .
RUN pip install --target ${FUNCTION_DIR} -r requirements.txt
RUN pip install --target ${FUNCTION_DIR} --no-cache-dir --force-reinstall pillow
#RUN pip install --target ${FUNCTION_DIR} --no-cache-dir --force-reinstall pillow
#RUN pip install --target ${FUNCTION_DIR} --force-reinstall pillow

# Multi-stage build: grab a fresh copy of the base image
#FROM mcr.microsoft.com/playwright/python:v1.51.0-jammy
FROM mcr.microsoft.com/playwright/python:v1.51.0-noble@sha256:a7d74e5d10e9a25b9c95cec1d702bdaa83a616e9c57b0c3f08e384c223da95df

# Include global arg in this stage of the build
ARG FUNCTION_DIR
# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

# Copy in the built dependencies
COPY --from=build-image ${FUNCTION_DIR} ${FUNCTION_DIR}

#COPY containerFastApi/. .

RUN mkdir -p /rpApi
COPY rpApi/*.py /rpApi/.

COPY shared/*.py /shared/.
COPY shared/db/ /shared/db/
COPY shared/messaging/ /shared/messaging/
COPY shared/orgRelated/ /shared/orgRelated/

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["refPortalFastApi.handler"]