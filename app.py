from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import json
import time
import pickle
import numpy as np

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# -----------------------------
# Friend Chat GPT-3.5 Turbo Setup
# -----------------------------
API_KEY = "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"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

def chat_with_openrouter(user_message):
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
        return data['choices'][0]['message']['content'].strip()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 429:
            print("⚠️ Rate limit exceeded, waiting 5 seconds...")
            time.sleep(5)
            return chat_with_openrouter(user_message)
        else:
            return "I'm having trouble connecting right now. Please try again in a moment."
    except Exception as e:
        return "I'm experiencing some technical difficulties. Please try again."

# -----------------------------
# Autism Screening ML Setup
# -----------------------------
# Load trained model
ml_model = pickle.load(open("autism_model.pkl", "rb"))

# -----------------------------
# Routes
# -----------------------------

# Home route for Discover Page
@app.route("/")
def home():
    return render_template("index.html")

@app.route('/calm')
def calm():
    return render_template("calm.html")

@app.route('/friend')
def friend():
    return render_template("friend.html")

@app.route('/learn')
def learn():
    return render_template("learn.html")

@app.route('/shine')
def shine():
    return render_template("shine.html")

@app.route('/result')
def result():
    return render_template("result.html")

# Optional index route
@app.route("/discover")
def discover():
    return render_template("discover.html")


# Predict Autism% route
@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = [int(request.form[f"Q{i}"]) for i in range(1, 11)]
        final_input = np.array(data).reshape(1, -1)
        prediction = ml_model.predict(final_input)[0]
        prediction = round(prediction, 2)
        return render_template("result.html", prediction=prediction)
    except Exception as e:
        return f"Error: {e}"

# Friend Chat API health check
@app.route("/health")
def health():
    return jsonify({'status': 'healthy'})

# Friend Chat API
@app.route("/api/chat", methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        mood = data.get('mood', '')
        
        print(f"Received message: {user_message}")
        print(f"User mood: {mood}")
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        reply = chat_with_openrouter(user_message)
        print(f"Sending reply: {reply}")
        return jsonify({'reply': reply})
    except Exception as e:
        print(f"Error in chat endpoint: {e}")
        return jsonify({'reply': "I'm having trouble processing your message right now. Please try again."})

# -----------------------------
# Run Flask
# -----------------------------
if __name__ == "__main__":
    print("Starting combined SafeSpace API...")
    print("Friend Chat API: /api/chat")
    print("Discover Page: / and /predict")
    app.run(debug=True, port=5000)
