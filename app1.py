from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import time
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Initialize SocketIO with async_mode
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Data storage (in production, use a proper database)
online_therapists = set()
client_requests = {}
active_sessions = {}
waiting_clients = set()

@app.route('/')
def index():
    return render_template('safeline1.html')

@app.route('/safeline')
def safeline():
    return render_template('safeline1.html')

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    
    # Remove from online therapists
    if request.sid in online_therapists:
        online_therapists.remove(request.sid)
        emit('therapist-offline', broadcast=True)
    
    # Remove client requests
    if request.sid in client_requests:
        del client_requests[request.sid]
    
    # Remove from waiting clients
    if request.sid in waiting_clients:
        waiting_clients.remove(request.sid)
    
    # Handle session cleanup
    session_to_remove = None
    for session_id, session in active_sessions.items():
        if request.sid in [session['client_sid'], session['therapist_sid']]:
            # Notify the other participant
            other_sid = session['therapist_sid'] if request.sid == session['client_sid'] else session['client_sid']
            if other_sid:
                emit('session-ended', room=other_sid)
                emit('user-left', room=other_sid)
            session_to_remove = session_id
            break
    
    if session_to_remove:
        del active_sessions[session_to_remove]

@socketio.on('therapist-online')
def handle_therapist_online():
    """Therapist comes online"""
    online_therapists.add(request.sid)
    print(f"Therapist {request.sid} is now online")
    emit('status-update', {'message': 'You are now online'}, room=request.sid)

@socketio.on('therapist-offline')
def handle_therapist_offline():
    """Therapist goes offline"""
    if request.sid in online_therapists:
        online_therapists.remove(request.sid)
    print(f"Therapist {request.sid} went offline")
    emit('status-update', {'message': 'You are now offline'}, room=request.sid)

@socketio.on('request-therapist')
def handle_request_therapist():
    """Client requests a therapist"""
    if not online_therapists:
        emit('error', {'message': 'No therapists available. Please try again later.'}, room=request.sid)
        return
    
    # Store client request
    client_requests[request.sid] = {
        'timestamp': time.time(),
        'status': 'waiting'
    }
    waiting_clients.add(request.sid)
    
    # Notify all online therapists
    emit('therapist-request', {
        'client_sid': request.sid,
        'timestamp': datetime.now().isoformat()
    }, broadcast=True)
    
    emit('request-sent', room=request.sid)
    print(f"Client {request.sid} requested a therapist")

@socketio.on('cancel-request')
def handle_cancel_request():
    """Client cancels their request"""
    if request.sid in client_requests:
        del client_requests[request.sid]
    if request.sid in waiting_clients:
        waiting_clients.remove(request.sid)
    emit('request-cancelled', room=request.sid)
    print(f"Client {request.sid} cancelled their request")

@socketio.on('accept-request')
def handle_accept_request(data):
    """Therapist accepts a client request"""
    client_sid = data.get('client_sid')
    
    if not client_sid or client_sid not in waiting_clients:
        emit('error', {'message': 'Client request no longer available'}, room=request.sid)
        return
    
    # Create a session
    session_id = str(uuid.uuid4())[:8]
    active_sessions[session_id] = {
        'client_sid': client_sid,
        'therapist_sid': request.sid,
        'start_time': time.time(),
        'end_time': time.time() + 600,  # 10 minutes from now
        'status': 'active'
    }
    
    # Remove client from waiting
    waiting_clients.remove(client_sid)
    if client_sid in client_requests:
        del client_requests[client_sid]
    
    # Notify client
    emit('request-accepted', {
        'session_id': session_id,
        'therapist_sid': request.sid
    }, room=client_sid)
    
    # Notify therapist
    emit('session-started', {
        'session_id': session_id,
        'client_sid': client_sid
    }, room=request.sid)
    
    # Start session timer
    start_session_timer(session_id)
    
    print(f"Therapist {request.sid} accepted client {client_sid}, session: {session_id}")

@socketio.on('decline-request')
def handle_decline_request(data):
    """Therapist declines a client request"""
    client_sid = data.get('client_sid')
    
    if client_sid in waiting_clients:
        waiting_clients.remove(client_sid)
    
    if client_sid in client_requests:
        del client_requests[client_sid]
    
    emit('request-declined', room=client_sid)
    print(f"Therapist {request.sid} declined client {client_sid}")

# WebRTC Signaling
@socketio.on('offer')
def handle_offer(data):
    """Handle WebRTC offer"""
    session_id = find_session_by_participant(request.sid)
    if session_id:
        session = active_sessions[session_id]
        target_sid = session['client_sid'] if request.sid == session['therapist_sid'] else session['therapist_sid']
        emit('offer', {
            'offer': data['offer'],
            'from_sid': request.sid
        }, room=target_sid)

@socketio.on('answer')
def handle_answer(data):
    """Handle WebRTC answer"""
    session_id = find_session_by_participant(request.sid)
    if session_id:
        session = active_sessions[session_id]
        target_sid = session['client_sid'] if request.sid == session['therapist_sid'] else session['therapist_sid']
        emit('answer', {
            'answer': data['answer'],
            'from_sid': request.sid
        }, room=target_sid)

@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    """Handle ICE candidate"""
    session_id = find_session_by_participant(request.sid)
    if session_id:
        session = active_sessions[session_id]
        target_sid = session['client_sid'] if request.sid == session['therapist_sid'] else session['therapist_sid']
        emit('ice-candidate', {
            'candidate': data['candidate'],
            'from_sid': request.sid
        }, room=target_sid)

@socketio.on('end-session')
def handle_end_session():
    """End the current session"""
    session_id = find_session_by_participant(request.sid)
    if session_id:
        session = active_sessions[session_id]
        
        # Notify both participants
        emit('session-ended', room=session['client_sid'])
        emit('session-ended', room=session['therapist_sid'])
        
        # Clean up
        del active_sessions[session_id]
        print(f"Session {session_id} ended by {request.sid}")

# Helper functions
def find_session_by_participant(sid):
    """Find session ID by participant socket ID"""
    for session_id, session in active_sessions.items():
        if sid in [session['client_sid'], session['therapist_sid']]:
            return session_id
    return None

def start_session_timer(session_id):
    """Start a timer for the session (10 minutes)"""
    def end_session():
        time.sleep(600)  # 10 minutes
        if session_id in active_sessions:
            session = active_sessions[session_id]
            emit('session-ended', room=session['client_sid'])
            emit('session-ended', room=session['therapist_sid'])
            del active_sessions[session_id]
            print(f"Session {session_id} ended automatically after 10 minutes")
    
    timer_thread = threading.Thread(target=end_session)
    timer_thread.daemon = True
    timer_thread.start()

# API endpoints for status checking
@app.route('/api/status')
def get_status():
    """Get current system status"""
    return jsonify({
        'online_therapists': len(online_therapists),
        'waiting_clients': len(waiting_clients),
        'active_sessions': len(active_sessions),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/sessions')
def get_sessions():
    """Get active sessions (admin view)"""
    sessions_data = {}
    for session_id, session in active_sessions.items():
        time_remaining = max(0, session['end_time'] - time.time())
        sessions_data[session_id] = {
            'client_sid': session['client_sid'],
            'therapist_sid': session['therapist_sid'],
            'time_remaining_seconds': int(time_remaining),
            'time_remaining_formatted': format_time_remaining(time_remaining)
        }
    return jsonify(sessions_data)

def format_time_remaining(seconds):
    """Format seconds into MM:SS format"""
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes:02d}:{seconds:02d}"

if __name__ == '__main__':
    print("Starting SafeLine Server...")
    print("Available routes:")
    print("  /safeline - SafeLine video call interface")
    print("  /api/status - System status")
    print("  /api/sessions - Active sessions")
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)