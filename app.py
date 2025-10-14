from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_cors import CORS
import requests
import json
import time
import pickle
import numpy as np
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename

# -------------------------
# APP SETUP
# -------------------------
app = Flask(__name__)
CORS(app)
app.secret_key = 'your-secret-key-here'

# -------------------------
# CONFIGURATION
# -------------------------
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'txt', 'doc', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB_PATH = 'safespace.db'  # single DB for the project

# -------------------------
# DATABASE INITIALIZATION
# -------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS shine_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    title TEXT,
                    description TEXT,
                    file_path TEXT,
                    likes INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

init_db()

# -------------------------
# HELPER FUNCTIONS
# -------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# -------------------------
# GPT FRIEND CHAT SETUP
# -------------------------
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
            print("⚠️ Rate limit exceeded, retrying...")
            time.sleep(5)
            return chat_with_openrouter(user_message)
        else:
            return "I'm having trouble connecting right now. Please try again later."
    except Exception as e:
        return "I'm experiencing some technical difficulties. Please try again."


# -------------------------
# ML MODEL SETUP
# -------------------------
ml_model = pickle.load(open("autism_model.pkl", "rb"))


# -------------------------
# ROUTES
# -------------------------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/learn')
def learn():
    return render_template('learn.html')

@app.route('/calm')
def calm():
    return render_template('calm.html')

@app.route('/discover')
def discover():
    return render_template('discover.html')

@app.route('/friend')
def friend():
    return render_template('friend.html')

# -------------------------
# DISCOVER PAGE - PREDICT AUTISM %
# -------------------------
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


# -------------------------
# FRIEND CHAT API
# -------------------------
@app.route("/api/chat", methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        mood = data.get('mood', '')

        if not user_message:
            return jsonify({'error': 'No message provided'}), 400

        reply = chat_with_openrouter(user_message)
        return jsonify({'reply': reply})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'reply': "Sorry, I'm having trouble responding right now."})


# -------------------------
# SHINE PAGE
# -------------------------
@app.route('/shine')
def shine():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM shine_submissions ORDER BY datetime(created_at) DESC")
    submissions = c.fetchall()
    conn.close()

    formatted_submissions = []
    for sub in submissions:
        sub = list(sub)
        try:
            sub[6] = datetime.strptime(sub[6], "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        formatted_submissions.append(sub)

    return render_template("shine.html", submissions=formatted_submissions)


@app.route('/shine/like/<int:submission_id>', methods=['POST'])
def shine_like(submission_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE shine_submissions SET likes = likes + 1 WHERE id = ?", (submission_id,))
    conn.commit()

    c.execute("SELECT likes FROM shine_submissions WHERE id = ?", (submission_id,))
    likes = c.fetchone()[0]
    conn.close()

    return {"success": True, "likes": likes}


@app.route('/shine/submit', methods=['POST'])
def shine_submit():
    username = request.form['username']
    title = request.form['title']
    description = request.form.get('description', '')
    file = request.files['file']

    if not username or not title or not file:
        flash('Please fill in all required fields.', 'error')
        return redirect(url_for('shine'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO shine_submissions (username, title, description, file_path, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, title, description, file_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()

        flash('Your talent has been shared successfully!', 'success')
    else:
        flash('Invalid file type. Please upload a supported format.', 'error')

    return redirect(url_for('shine'))


# -------------------------
# HEALTH CHECK
# -------------------------
@app.route("/health")
def health():
    return jsonify({'status': 'healthy'})


# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    print("🚀 SafeSpace Backend Running")
    print("Pages: /learn /calm /discover /friend /shine")
    app.run(debug=True, host="0.0.0.0", port=5000)
