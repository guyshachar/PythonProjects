from postpy2.core import PostPython
import os

# Define the path to your exported Postman Collection JSON file
# Make sure this path is correct relative to where your Python script is
collection_path = './adhoc/ManyChat API.postman_collection.json' 

# Define the path to your exported Postman Environment JSON file (optional)
environment_path = 'path/to/your/exported_environment.json' 

# --- Initialize PostPython ---
# The PostPython instance is your gateway to the collection
runner = PostPython(collection_path)

# --- Load Environment Variables (Optional) ---
# If you have an environment file, load it.
# This will make your {{variable_name}} available in your requests.
if os.path.exists(environment_path):
    runner.environments.load(environment_path)
    print(f"Loaded environment from: {environment_path}")
else:
    print(f"Environment file not found at: {environment_path}. Skipping environment load.")

# You can also update environment variables directly in your script
runner.environments.update({'BASE_URL': 'http://localhost:8000/api'})
runner.environments.update({'AUTH_TOKEN': 'your_dynamic_token_here'})
print(f"Current environment variables: {runner.environments.to_dict()}")

# --- How to Call Your Requests ---

# Postpy2 organizes your requests based on folders in your Postman collection.
# - Folder names become attributes of the 'runner' object, capitalized (UpperCamelCase).
# - Request names become methods of those folder objects, lowercase (snake_case).
# - If a request is directly in the collection (not in a folder), it's under 'runner.default'.

# Example: Assuming your collection has a folder named "User Management"
# and inside it, a request named "Get User By ID" and "Create New User"

# 1. Calling a request inside a folder:
try:
    print("\n--- Executing 'Get User By ID' ---")
    # Access the folder (UserManagement) then the request (get_user_by_id)
    # The arguments are the same as Postman path variables or query parameters
    # if they are defined in your request URL.
    # E.g., if URL is {{BASE_URL}}/users/:id, you pass id=123
    get_user_response = runner.UserManagement.get_user_by_id(id='123') 
    
    print(f"Status Code: {get_user_response.status_code}")
    print(f"Response Body: {get_user_response.json()}")

except AttributeError as e:
    print(f"Error calling request: {e}. Check folder/request names and arguments.")
    print("Use runner.help() to see available requests.")
except Exception as e:
    print(f"An unexpected error occurred:", e)


# 2. Calling a request that takes a JSON body (e.g., POST, PUT)
try:
    print("\n--- Executing 'Create New User' ---")
    user_data = {
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "password": "secure_password_123"
    }
    # Pass the body as 'json' argument (for JSON payloads) or 'data' (for form data)
    create_user_response = runner.UserManagement.create_new_user(json=user_data)

    print(f"Status Code: {create_user_response.status_code}")
    print(f"Response Body: {create_user_response.json()}")

except AttributeError as e:
    print(f"Error calling request: {e}. Check folder/request names and arguments.")
except Exception as e:
    print(f"An unexpected error occurred:", e)


# 3. Calling a request directly in the collection (no folder)
# If you have a request named "Health Check" directly in your collection:
try:
    print("\n--- Executing 'Health Check' ---")
    health_check_response = runner.default.health_check()
    print(f"Status Code: {health_check_response.status_code}")
    print(f"Response Body: {health_check_response.text}") # Might be plain text
except AttributeError as e:
    print(f"Error calling request: {e}. Check folder/request names and arguments.")
except Exception as e:
    print(f"An unexpected error occurred:", e)

# --- Listing Available Requests ---
# If you're unsure about the exact naming conversion, use the help() method:
print("\n--- Available Requests (from runner.help()) ---")
runner.help()

# --- Overriding Request Properties (e.g., headers for a specific call) ---
# You can override headers or other properties for a specific request execution
print("\n--- Executing 'Get User By ID' with custom header ---")
custom_headers = {"X-Custom-Header": "MyValue"}
get_user_response_with_header = runner.UserManagement.get_user_by_id(id='123', headers=custom_headers)
print(f"Status Code (with custom header): {get_user_response_with_header.status_code}")