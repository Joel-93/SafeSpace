# app_combined.py
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import requests
import json
import os
import sqlite3
import time
import pickle
import numpy as np
from datetime import datetime

# -------------------------
# Configuration
# -------------------------
APP_SECRET_KEY = os.getenv("SAFESPACE_SECRET_KEY", "safespace_secret_key")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "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")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'txt', 'doc', 'docx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USERS_DB = 'users.db'           # SQLAlchemy DB for users
SHINE_DB = 'safespace.db'       # sqlite3 DB for shine submissions
ML_MODEL_PATH = "autism_model.pkl"  # optional ML model (pickle)

# -------------------------
# Flask setup
# -------------------------
app = Flask(__name__)
CORS(app)
app.secret_key = APP_SECRET_KEY

# SQLAlchemy (users)
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, USERS_DB)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -------------------------
# SQLAlchemy User model
# -------------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    firstName = db.Column(db.String(100))
    lastName = db.Column(db.String(100))
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(20))
    dateOfBirth = db.Column(db.String(20))

# -------------------------
# Shine sqlite3 DB init
# -------------------------
def init_shine_db():
    conn = sqlite3.connect(SHINE_DB)
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

init_shine_db()

# -------------------------
# Helper functions
# -------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_shine_submissions():
    conn = sqlite3.connect(SHINE_DB)
    c = conn.cursor()
    c.execute("SELECT id, username, title, description, file_path, likes, created_at FROM shine_submissions ORDER BY datetime(created_at) DESC")
    rows = c.fetchall()
    conn.close()
    return rows

# -------------------------
# Load ML model (optional)
# -------------------------
ml_model = None
if os.path.exists(ML_MODEL_PATH):
    try:
        ml_model = pickle.load(open(ML_MODEL_PATH, "rb"))
        app.logger.info("ML model loaded from %s", ML_MODEL_PATH)
    except Exception as e:
        app.logger.warning("Failed to load ML model: %s", e)
else:
    app.logger.info("ML model file not found; /predict will be disabled.")

# -------------------------
# OpenRouter / Friend chat
# -------------------------
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
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(OPENROUTER_URL, headers=headers, data=json.dumps(payload), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        # support both openrouter and openai shaped responses
        # try common paths
        if 'choices' in data and len(data['choices']) > 0:
            # openrouter often returns choices[0].message.content
            choice = data['choices'][0]
            if 'message' in choice and 'content' in choice['message']:
                return choice['message']['content'].strip()
            elif 'text' in choice:
                return choice['text'].strip()
        # fallback: try top-level fields
        if 'reply' in data:
            return data['reply']
        return "Sorry — couldn't parse response from AI."
    except requests.exceptions.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        app.logger.error("HTTP error from OpenRouter: %s (status=%s)", e, status)
        if status == 429:
            time.sleep(2)
            return chat_with_openrouter(user_message)
        return "I'm having trouble connecting right now. Please try again later."
    except Exception as e:
        app.logger.exception("Error calling OpenRouter: %s", e)
        return "I'm having trouble connecting right now. Please try again later."

# -------------------------
# Routes: pages
# -------------------------
@app.route('/')
def home():
    # If logged in, go to index; else show login/register page
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/index')
def index():
    if 'user_id' not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for('home'))
    return render_template('index.html', name=session.get('user_name'))

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

@app.route('/safeline')
def safeline():
    return render_template('safeline.html')

@app.route('/shine')
def shine():
    # Connect to the Shine SQLite DB
    conn = sqlite3.connect(SHINE_DB)
    c = conn.cursor()
    c.execute("SELECT id, username, title, description, file_path, likes, created_at FROM shine_submissions ORDER BY datetime(created_at) DESC")
    submissions = c.fetchall()
    conn.close()

    # Convert string dates to datetime objects
    submissions_fixed = []
    for sub in submissions:
        try:
            date_obj = datetime.strptime(sub[6], '%Y-%m-%d %H:%M:%S')  # full timestamp format
        except Exception:
            date_obj = None
        submissions_fixed.append(sub[:6] + (date_obj,))  # keep other columns

    # Render template with converted dates
    return render_template('shine.html', submissions=submissions_fixed)



# -------------------------
# Authentication endpoints (register/login/logout)
# -------------------------
@app.route('/register', methods=['POST'])
def register():
    # Fields from your login.html register form
    firstName = request.form.get('firstName')
    lastName = request.form.get('lastName')
    email = request.form.get('email')
    password = request.form.get('password')
    gender = request.form.get('gender')
    dateOfBirth = request.form.get('dateOfBirth')

    if not email or not password:
        flash("Email and password required.", "danger")
        return redirect(url_for('home'))

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("Email already registered. Please login instead.", "warning")
        return redirect(url_for('home'))

    hashed_pw = generate_password_hash(password)
    new_user = User(firstName=firstName, lastName=lastName, email=email,
                    password=hashed_pw, gender=gender, dateOfBirth=dateOfBirth)
    db.session.add(new_user)
    db.session.commit()

    flash("Account created successfully! Please login.", "success")
    return redirect(url_for('home'))

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        flash("Invalid email or password. Try again.", "danger")
        return redirect(url_for('home'))

    session['user_id'] = user.id
    session['user_name'] = user.firstName
    flash("Login successful!", "success")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('home'))

# -------------------------
# View users (admin-ish)
# -------------------------
@app.route('/view_users')
def view_users():
    if 'user_id' not in session:
        flash("Please log in first to view users.", "warning")
        return redirect(url_for('home'))
    users = User.query.all()
    return render_template('view_users.html', users=users)

# -------------------------
# Shine endpoints (upload, like)
# -------------------------
@app.route('/shine/submit', methods=['POST'])
def shine_submit():
    if 'user_id' not in session:
        flash("Please log in first to submit.", "warning")
        return redirect(url_for('home'))

    username = request.form.get('username') or session.get('user_name') or "Anonymous"
    title = request.form.get('title')
    description = request.form.get('description', '')
    file = request.files.get('file')

    if not username or not title or not file:
        flash('Please fill in all required fields and attach a file.', 'error')
        return redirect(url_for('shine'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{filename}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)

        conn = sqlite3.connect(SHINE_DB)
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

@app.route('/shine/like/<int:submission_id>', methods=['POST'])
def shine_like(submission_id):
    conn = sqlite3.connect(SHINE_DB)
    c = conn.cursor()
    c.execute("UPDATE shine_submissions SET likes = likes + 1 WHERE id = ?", (submission_id,))
    conn.commit()
    c.execute("SELECT likes FROM shine_submissions WHERE id = ?", (submission_id,))
    likes = c.fetchone()[0]
    conn.close()
    return jsonify({"success": True, "likes": likes})

# Serve uploaded files
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -------------------------
# Friend chat API (frontend -> this backend -> OpenRouter)
# -------------------------
@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def api_chat():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        payload = request.get_json() or {}
        user_message = payload.get('message') or payload.get('text') or ""
        mood = payload.get('mood')
        if not user_message:
            return jsonify({"error": "No message provided"}), 400
        reply = chat_with_openrouter(user_message)
        return jsonify({"reply": reply})
    except Exception as e:
        app.logger.exception("Chat error: %s", e)
        return jsonify({"reply": "Sorry, I'm having trouble responding right now."}), 500

# -------------------------
# Discover -> ML predict
# -------------------------
@app.route('/predict', methods=['POST'])
def predict():
    if ml_model is None:
        return jsonify({"error": "ML model not available on server."}), 500
    try:
        # expecting form fields Q1..Q10 or Q1..Q10 numerically
        data = []
        for i in range(1, 11):
            key = f"Q{i}"
            val = request.form.get(key)
            if val is None:
                return jsonify({"error": f"Missing question {key}"}), 400
            data.append(int(val))
        final_input = np.array(data).reshape(1, -1)
        prediction = ml_model.predict(final_input)[0]
        prediction = float(np.round(prediction, 2))
        return render_template("result.html", prediction=prediction)
    except Exception as e:
        app.logger.exception("Predict error: %s", e)
        return jsonify({"error": str(e)}), 500

# -------------------------
# Health check
# -------------------------
@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

# -------------------------
# Before request: (optional) clear session when debug and landing on home
# -------------------------
@app.before_request
def maybe_clear_session():
    # Do not auto-clear sessions in production; this was in your earlier code for debug
    if app.debug and request.endpoint == 'home':
        # keep as-is or comment out if undesired
        pass

# -------------------------
# Create DBs and run
# -------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()   # create users table if needed
    app.run(host="0.0.0.0", port=5000, debug=True)
