from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os

# --------------------
# Flask Setup
# --------------------
app = Flask(__name__)
app.secret_key = "safespace_secret_key"

# --------------------
# Database Setup
# --------------------
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(base_dir, 'users.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --------------------
# User Model
# --------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    firstName = db.Column(db.String(100))
    lastName = db.Column(db.String(100))
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(20))
    dateOfBirth = db.Column(db.String(20))

# --------------------
# Routes
# --------------------

@app.route('/')
def home():
    # Redirect logged-in users to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

# -------------------- Register --------------------
@app.route('/register', methods=['POST'])
def register():
    firstName = request.form.get('firstName')
    lastName = request.form.get('lastName')
    email = request.form.get('email')
    password = request.form.get('password')
    gender = request.form.get('gender')
    dateOfBirth = request.form.get('dateOfBirth')

    # Check if user already exists
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("Email already registered. Please log in instead.", "warning")
        return redirect(url_for('home'))

    # Hash password
    hashed_pw = generate_password_hash(password)

    # Save new user
    new_user = User(
        firstName=firstName,
        lastName=lastName,
        email=email,
        password=hashed_pw,
        gender=gender,
        dateOfBirth=dateOfBirth
    )
    db.session.add(new_user)
    db.session.commit()

    flash("Account created successfully! Please log in.", "success")
    return redirect(url_for('home'))

# -------------------- Login --------------------
@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    user = User.query.filter_by(email=email).first()

    # Check credentials
    if not user or not check_password_hash(user.password, password):
        flash("Invalid email or password. Try again.", "danger")
        return redirect(url_for('home'))

    # Login success
    session['user_id'] = user.id
    session['user_name'] = user.firstName
    flash("Login successful!", "success")
    return redirect(url_for('index'))

# -------------------- Index --------------------
@app.route('/index')
def index():
    if 'user_id' not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for('home'))
    return render_template('index.html', name=session.get('user_name'))

# -------------------- Logout --------------------
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('home'))

# --------------------
# Extra Pages (Fix for BuildError)
# --------------------
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

@app.route('/shine')
def shine():
    return render_template('shine.html')

@app.route('/view_users')
def view_users():
    if 'user_id' not in session:
        flash("Please log in first to view users.", "warning")
        return redirect(url_for('home'))
    
    users = User.query.all()
    return render_template('view_users.html', users=users)

@app.before_request
def clear_session_on_start():
    if app.debug and request.endpoint == 'home':
        session.clear()


# --------------------
# Run the App
# --------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=8000, debug=True)
