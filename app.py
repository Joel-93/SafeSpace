from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
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
import threading
import uuid

# -------------------------
# Configuration
# -------------------------
APP_SECRET_KEY = os.getenv("SAFESPACE_SECRET_KEY", "safespace_secret_key")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "xxxxx")
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'pdf', 'txt', 'doc', 'docx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USERS_DB = 'users.db'           # SQLAlchemy DB for users
SHINE_DB = 'safespace.db'       # sqlite3 DB for shine submissions
ML_MODEL_PATH = "autism_model.pkl"  # optional ML model (pickle)

# -------------------------
# Flask & SocketIO setup
# -------------------------
app = Flask(__name__)
CORS(app)
app.secret_key = APP_SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# SQLAlchemy (users)
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, USERS_DB)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# -------------------------
# SafeLine State Management
# -------------------------
online_therapists = set()
pending_requests = {}      # client_sid -> therapist_sid
active_sessions = {}       # sid -> partner_sid

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
        "model": "openai/gpt-3.5-turbo-instruct",
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
        resp = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=20
        )

        # ✅ DEBUG LINE — THIS IS WHERE IT GOES
        print("OPENROUTER RESPONSE:", resp.status_code, resp.text)
        print("OPENROUTER STATUS:", resp.status_code)
        print("OPENROUTER BODY:", resp.text)
        
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        print("OpenRouter ERROR:", e)
        return "I'm having trouble connecting right now. Please try again later."

# -------------------------
# SafeLine Auto-End Session
# -------------------------
def auto_end_session(client_sid, therapist_sid):
    time.sleep(600)  # 10 minutes
    if client_sid in active_sessions:
        active_sessions.pop(client_sid, None)
        active_sessions.pop(therapist_sid, None)
        emit("session-ended", room=client_sid)
        emit("session-ended", room=therapist_sid)
        app.logger.info("Session auto-ended for %s and %s", client_sid, therapist_sid)

# -------------------------
# Routes: pages
# -------------------------
@app.route('/')
def home():
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
    conn = sqlite3.connect(SHINE_DB)
    c = conn.cursor()
    c.execute("SELECT id, username, title, description, file_path, likes, created_at FROM shine_submissions ORDER BY datetime(created_at) DESC")
    submissions = c.fetchall()
    conn.close()

    submissions_fixed = []
    for sub in submissions:
        try:
            date_obj = datetime.strptime(sub[6], '%Y-%m-%d %H:%M:%S')
        except Exception:
            date_obj = None
        submissions_fixed.append(sub[:6] + (date_obj,))

    return render_template('shine.html', submissions=submissions_fixed)

# -------------------------
# Authentication endpoints
# -------------------------
@app.route('/register', methods=['POST'])
def register():
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
# View users
# -------------------------
@app.route('/view_users')
def view_users():
    if 'user_id' not in session:
        flash("Please log in first to view users.", "warning")
        return redirect(url_for('home'))
    users = User.query.all()
    return render_template('view_users.html', users=users)

# -------------------------
# Shine endpoints
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

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -------------------------
# Friend chat API
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
# Socket.IO Event Handlers
# -------------------------
@socketio.on('connect')
def handle_connect():
    app.logger.info("Client connected: %s", request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info("Client disconnected: %s", request.sid)
    online_therapists.discard(request.sid)
    pending_requests.pop(request.sid, None)

    partner = active_sessions.pop(request.sid, None)
    if partner:
        active_sessions.pop(partner, None)
        emit("session-ended", room=partner)

# -------------------------
# SafeLine: Therapist Events
# -------------------------
@socketio.on('therapist-online')
def handle_therapist_online():
    online_therapists.add(request.sid)
    app.logger.info("Therapist online: %s", request.sid)

@socketio.on('therapist-offline')
def handle_therapist_offline():
    online_therapists.discard(request.sid)

@socketio.on('accept-request')
def handle_accept_request(data):
    client_sid = data.get('clientId')
    if not client_sid or client_sid not in pending_requests:
        return

    therapist_sid = request.sid
    active_sessions[client_sid] = therapist_sid
    active_sessions[therapist_sid] = client_sid
    pending_requests.pop(client_sid, None)

    emit('request-accepted', {'role': 'client'}, room=client_sid)
    emit('request-accepted', {'role': 'therapist'}, room=therapist_sid)

    threading.Thread(target=auto_end_session, args=(client_sid, therapist_sid), daemon=True).start()

@socketio.on('decline-request')
def handle_decline_request(data):
    client_sid = data.get('clientId')
    if client_sid:
        emit('request-declined', room=client_sid)
        pending_requests.pop(client_sid, None)

# -------------------------
# SafeLine: Client Events
# -------------------------
@socketio.on('request-therapist')
def handle_request_therapist():
    if not online_therapists:
        emit('error', {'message': 'No therapists available'}, room=request.sid)
        return

    therapist_sid = list(online_therapists)[0]
    pending_requests[request.sid] = therapist_sid

    emit('therapist-request', {'clientId': request.sid}, room=therapist_sid)
    emit('request-sent', room=request.sid)

@socketio.on('cancel-request')
def handle_cancel_request():
    pending_requests.pop(request.sid, None)

# -------------------------
# SafeLine: WebRTC Signaling
# -------------------------
@socketio.on('offer')
def handle_offer(data):
    target = active_sessions.get(request.sid)
    if target:
        emit('offer', {
            'offer': data['offer'],
            'from': request.sid
        }, room=target)

@socketio.on('answer')
def handle_answer(data):
    target = active_sessions.get(request.sid)
    if target:
        emit('answer', {
            'answer': data['answer'],
            'from': request.sid
        }, room=target)

@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    target = active_sessions.get(request.sid)
    if target:
        emit('ice-candidate', {
            'candidate': data['candidate'],
            'from': request.sid
        }, room=target)

@socketio.on('end-session')
def handle_end_session():
    partner = active_sessions.pop(request.sid, None)
    if partner:
        active_sessions.pop(partner, None)
        emit('session-ended', room=partner)

# -------------------------
# Create DBs and run
# -------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.logger.info("🚀 SafeSpace is running")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
    
    
#git add .
#git commit -m ""
#git push
#nohup python3 app.py &