# Define custom function directory
ARG FUNCTION_DIR="/function"

# Use the AWS Lambda base image for Python 3.12
FROM public.ecr.aws/lambda/python:3.13

# copy requirements.txt to container root directory
COPY containerEventBridge/requirements.txt ./

# installing dependencies from the requirements under the root directory
RUN pip3 install -r ./requirements.txt

# Copy function code to container
COPY containerEventBridge/lambda_function.py ./

COPY shared/*.py shared/.
COPY shared/db/ shared/db/
COPY shared/messaging/ shared/messaging/
COPY shared/orgRelated/ shared/orgRelated/

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "lambda_function.lambda_handler" ]