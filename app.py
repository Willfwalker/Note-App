from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime
import json
import os
from dotenv import load_dotenv
from functools import wraps

# Initialize Flask app without static files
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key')

# Load environment variables
load_dotenv()

# Initialize Firebase immediately
try:
    firebase_credentials_json = os.getenv('FIREBASE_CREDENTIALS')
    if not firebase_credentials_json:
        raise ValueError("FIREBASE_CREDENTIALS environment variable not set")
    
    cred_dict = json.loads(firebase_credentials_json)
    if 'private_key' in cred_dict:
        cred_dict['private_key'] = cred_dict['private_key'].replace('\\n', '\n')
    
    cred = credentials.Certificate(cred_dict)
    firebase_app = firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully")
except Exception as e:
    print(f"Firebase initialization error: {str(e)}")
    raise

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/verify_token', methods=['POST'])
def verify_token():
    try:
        id_token = request.json['idToken']
        decoded_token = auth.verify_id_token(id_token)
        user_id = decoded_token['uid']
        session['user_id'] = user_id
        return jsonify({'success': True})
    except Exception as e:
        print(f"Token verification error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    tasks_ref = db.collection('tasks').where('user_id', '==', user_id).order_by('created_at', direction=firestore.Query.DESCENDING)
    tasks = []
    for doc in tasks_ref.stream():
        task = doc.to_dict()
        task['id'] = doc.id
        tasks.append(task)
    return render_template('index.html', tasks=tasks)

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    user_id = session['user_id']
    title = request.form.get('title')
    description = request.form.get('description')
    
    if title:
        task = {
            'title': title,
            'description': description,
            'completed': False,
            'created_at': datetime.now(),
            'user_id': user_id
        }
        db.collection('tasks').add(task)
    return redirect(url_for('index'))

@app.route('/toggle_task/<task_id>', methods=['POST'])
def toggle_task(task_id):
    task_ref = db.collection('tasks').document(task_id)
    task = task_ref.get()
    if task.exists:
        current_status = task.to_dict()['completed']
        task_ref.update({'completed': not current_status})
    return redirect(url_for('index'))

@app.route('/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    db.collection('tasks').document(task_id).delete()
    return redirect(url_for('index'))

@app.errorhandler(Exception)
def handle_error(error):
    print(f"Error occurred: {str(error)}")
    return jsonify({
        'success': False,
        'error': str(error)
    }), 500
