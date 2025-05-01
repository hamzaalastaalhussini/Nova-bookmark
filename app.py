from flask import Flask, request, jsonify, render_template, redirect, session
from flask_cors import CORS
import google.generativeai as genai
import os
import re
from datetime import timedelta
import json
import bcrypt
from functools import wraps
import pytesseract
from PIL import Image
import io
import base64
import secrets
import time

app = Flask(__name__)
# Add bigideasmath.com to the allowed origins for /ask and /data
CORS(app, resources={
    r"/ask": {"origins": ["https://portal.achieve3000.com", "https://www.deltamath.com", "https://www.bigideasmath.com"]},
    r"/set_article": {"origins": "https://portal.achieve3000.com"},
    r"/data": {"origins": ["https://portal.achieve3000.com", "https://www.bigideasmath.com"]} # Changed to a list to include multiple origins
})

# Configure session
app.secret_key = os.getenv('SECRET_KEY') or os.urandom(24)
app.permanent_session_lifetime = timedelta(minutes=30)

# Initialize password hash from environment variable
PASSWORD = os.getenv('APP_PASSWORD')
if not PASSWORD:
    raise ValueError("APP_PASSWORD is not set in environment variables.")

SALT = bcrypt.gensalt(rounds=12)
HASHED_PASSWORD = bcrypt.hashpw(PASSWORD.encode('utf-8'), SALT)

# Add verification codes storage
verification_codes = {}  # Store active verification codes and their expiration times

def generate_verification_code():
    """Generate a random 6-digit verification code that expires in 5 minutes."""
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    expiration = time.time() + 300  # 5 minutes from now
    verification_codes[code] = expiration
    return code

def verify_code(code):
    """Verify if a code is valid and not expired."""
    if code in verification_codes:
        if time.time() < verification_codes[code]:
            # Code is valid and not expired
            del verification_codes[code]  # Remove the code after use
            return True
        else:
            # Code has expired
            del verification_codes[code]
    return False

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth or not check_auth(auth):
            return jsonify({'error': 'Unauthorized access'}), 401
        return f(*args, **kwargs)
    return decorated

def check_auth(auth_header):
    try:
        if not auth_header.startswith('Bearer '):
            return False
        password = auth_header.split(' ')[1]
        return bcrypt.checkpw(password.encode('utf-8'), HASHED_PASSWORD)
    except Exception:
        return False

# Securely load the API key from an environment variable
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is not set in environment variables.")

genai.configure(api_key=api_key)

# Initialize the Gemini model
model = genai.GenerativeModel('gemini-2.0-flash-exp')

# Middleware to redirect to the specified URL unless on an endpoint
@app.before_request
def redirect_to_nova():
    # Check if the current endpoint is a valid route
    if request.endpoint is None:
        return redirect("https://cpmjaguar1234.github.io/nova")

ask_enabled = True  # Global variable to track the state of the /ask endpoint

@app.route('/ask-status', methods=['GET'])
def ask_status():
    return jsonify({'enabled': ask_enabled}), 200

@app.route('/toggle-ask', methods=['POST'])
def toggle_ask():
    global ask_enabled
    try:
        data = request.get_json()
        ask_enabled = data.get('enabled', True)
        return jsonify({'message': f'Ask endpoint {"enabled" if ask_enabled else "disabled"} successfully.'}), 200
    except Exception as e:
        app.logger.error(f'Error toggling ask endpoint: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/ask', methods=['GET', 'POST'])
def ask_gemini():
    if not ask_enabled:
        return jsonify({'error': 'Ask endpoint is currently disabled.'}), 403

    app.logger.info(f"Received {request.method} request at /ask")

    if request.method == 'POST':
        data = request.get_json()
        app.logger.info(f"POST data: {data}")

        # Handle image input
        if 'image' in data:
            try:
                # Decode base64 image
                image_data = base64.b64decode(data['image'])
                image = Image.open(io.BytesIO(image_data))

                # Resize image if it's too large to potentially speed up processing
                max_dimension = 1024
                if image.width > max_dimension or image.height > max_dimension:
                    image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                    app.logger.info(f"Resized image to {image.size}")

                # Convert to format Gemini API accepts
                image_bytes = io.BytesIO()
                # Ensure image is in RGB format before saving as PNG for compatibility
                if image.mode == 'RGBA' or image.mode == 'P':
                    image = image.convert('RGB')
                image.save(image_bytes, format='PNG')
                image_bytes = image_bytes.getvalue()

                # Create multimodal prompt
                prompt = [
                    {"mime_type": "image/png", "data": image_bytes},
                    data.get('q', "Always give me only the final, fully simplified answer - no steps, no explanations, no extra text. Do this every time. If math, give the number answer, if reading, give me the letter answer, if the question asks when something happened, look at the dates in the text.")
                ]

                response = model.generate_content(prompt)
                if response and hasattr(response, 'text'):
                    cleaned_response = re.sub(r'\s+', ' ', response.text).strip()
                    app.logger.info(f"Generated response for image: {cleaned_response}")
                    return jsonify({'response': cleaned_response})

            except Exception as e:
                app.logger.error(f"Error processing image: {str(e)}")
                return jsonify({'error': 'Error processing image'}), 500

        # Handle text input
        user_input = data.get('q')

        # If the request contains article content, store it in session
        article_content = data.get('article')
        if article_content:
            session['article_content'] = article_content
            app.logger.info("Article content stored in session")

    else:
        user_input = request.args.get('q')
        app.logger.info(f"GET query parameter: {user_input}")

    if not user_input:
        app.logger.warning('No query parameter provided')
        return jsonify({'error': 'No query parameter provided'}), 400

    # If this is a question and we have stored article content, combine them
    if session.get('article_content'):
        user_input = f"{session['article_content']}\n\n{user_input}"

    try:
        response = model.generate_content(user_input)
        if response and hasattr(response, 'text'):
            cleaned_response = re.sub(r'\s+', ' ', response.text).strip()
            app.logger.info(f"Generated response: {cleaned_response}")
            return jsonify({'response': cleaned_response})
        else:
            app.logger.error('Failed to generate a valid response')
            return jsonify({'error': 'Failed to generate a valid response'}), 500
    except Exception as e:
        app.logger.error(f"Error during response generation: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/data', methods=['GET', 'POST'])
def handle_data():
    data_file = 'data.json'
    app.logger.info(f"Data endpoint called with {request.method} method")

    # Ensure the data file exists
    if not os.path.exists(data_file):
        with open(data_file, 'w') as f:
            json.dump([], f)

    # For GET requests, require authentication
    if request.method == 'GET':
        auth = request.authorization
        if not auth or not bcrypt.checkpw(auth.password.encode('utf-8'), HASHED_PASSWORD):
            return jsonify({'error': 'Unauthorized access'}), 401, {'WWW-Authenticate': 'Basic realm="Login Required"'}

        # GET method to retrieve and display data
        try:
            with open(data_file, 'r') as f:
                data = json.load(f)
            return render_template('data.html', data=data)
        except Exception as e:
            app.logger.error(f'Error reading data: {str(e)}')
            return jsonify({'error': str(e)}), 500

    if request.method == 'POST':
        try:
            if not request.is_json:
                app.logger.error('Request content type is not application/json')
                return jsonify({'error': 'Content-Type must be application/json'}), 400

            data = request.get_json()
            if 'text' not in data:
                app.logger.error('No text provided in request')
                return jsonify({'error': 'Text data is required'}), 400

            # Read existing data
            with open(data_file, 'r') as f:
                existing_data = json.load(f)

            # Append new data
            existing_data.append(data['text'])

            # Write back to file
            with open(data_file, 'w') as f:
                json.dump(existing_data, f, indent=2)

            app.logger.info('Data successfully added')
            return jsonify({'success': True, 'message': 'Data added successfully'})

        except Exception as e:
            app.logger.error(f"Error processing data: {str(e)}")
            return jsonify({'error': str(e)}), 500

@app.route('/clear-data', methods=['POST'])
def clear_data():
    try:
        # Use a relative path or ensure the absolute path is correct for your environment
        data_file_path = os.path.join(os.getcwd(), 'data.json')  # Adjust the path as needed
        with open(data_file_path, 'w') as data_file:
            data_file.write('[]')  # Clear the data by writing an empty array
        return jsonify({'message': 'Data cleared successfully.'}), 200
    except Exception as e:
        app.logger.error(f'Error clearing data: {str(e)}')  # Log the error for debugging
        return jsonify({'error': str(e)}), 500

def ask_gemini_internal(user_input):
    try:
        response = model.generate_content(user_input)
        if response and hasattr(response, 'text'):
            cleaned_response = re.sub(r'\s+', ' ', response.text).strip()
            app.logger.info(f"Generated response: {cleaned_response}")
            return {'response': cleaned_response}
        else:
            app.logger.error('Failed to generate a valid response')
            return {'error': 'Failed to generate a valid response'}
    except Exception as e:
        app.logger.error(f"Error during response generation: {str(e)}")
        return {'error': 'Internal server error'}

@app.route('/generate-code', methods=['POST'])
@require_auth
def generate_code():
    """Generate a new verification code."""
    try:
        code = generate_verification_code()
        return jsonify({'code': code}), 200
    except Exception as e:
        app.logger.error(f'Error generating verification code: {str(e)}')
        return jsonify({'error': str(e)}), 500

@app.route('/verify-code', methods=['POST'])
def verify_code_endpoint():
    """Verify a submitted code."""
    try:
        data = request.get_json()
        if not data or 'code' not in data:
            return jsonify({'error': 'No code provided'}), 400
        
        if verify_code(data['code']):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Invalid or expired code'}), 401
    except Exception as e:
        app.logger.error(f'Error verifying code: {str(e)}')
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)