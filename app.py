from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# 🔹 Replace with your OpenRouter GPT-3.5 Turbo API key
API_KEY = "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"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

def chat_with_openrouter(user_message):
    """
    Sends user message to OpenRouter GPT-3.5 Turbo and returns the response.
    Handles rate limit errors gracefully.
    """
    # Create a supportive system prompt
    system_prompt = """You are a caring, empathetic friend for someone with autism. 
    Provide gentle, supportive responses. Use simple language and be understanding.
    Offer encouragement and practical coping strategies when appropriate.
    Keep responses conversational and warm."""
    
    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
        # Extract chatbot reply
        return data['choices'][0]['message']['content'].strip()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            # Too Many Requests: wait and retry
            print("⚠️ Rate limit exceeded, waiting 5 seconds...")
            time.sleep(5)
            return chat_with_openrouter(user_message)
        else:
            return f"I'm having trouble connecting right now. Please try again in a moment."
    except Exception as e:
        return f"I'm experiencing some technical difficulties. Please try again."

@app.route('/')
def home():
    return jsonify({
        'message': 'Friend Chat API is running!',
        'status': 'active',
        'endpoints': {
            '/api/chat': 'POST - Send chat messages'
        }
    })

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        # Handle preflight request
        return '', 200
    
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        mood = data.get('mood', '')
        
        print(f"Received message: {user_message}")
        print(f"User mood: {mood}")
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        # Get response from OpenRouter
        reply = chat_with_openrouter(user_message)
        
        print(f"Sending reply: {reply}")
        return jsonify({'reply': reply})
    
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return jsonify({'reply': "I'm having trouble processing your message right now. Please try again."})

@app.route('/health')
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    print("Starting Friend Chat API...")
    print("API will be available at: http://127.0.0.1:5000")
    print("Chat endpoint: http://127.0.0.1:5000/api/chat")
    app.run(debug=True, port=5000)