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
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    firebase_config = {
        'apiKey': os.getenv('FIREBASE_WEB_API_KEY'),
        'authDomain': os.getenv('FIREBASE_AUTH_DOMAIN'),
        'projectId': os.getenv('FIREBASE_PROJECT_ID'),
        'storageBucket': os.getenv('FIREBASE_STORAGE_BUCKET'),
        'messagingSenderId': os.getenv('FIREBASE_MESSAGING_SENDER_ID'),
        'appId': os.getenv('FIREBASE_APP_ID')
    }
    
    # Add this debug print
    print("Firebase Config being sent to template:", {
        **firebase_config,
        'apiKey': firebase_config['apiKey'][:10] + '...' if firebase_config['apiKey'] else None
    })
    
    return render_template('login.html', firebase_config=firebase_config)

@app.route('/verify_token', methods=['POST'])
def verify_token():
    try:
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Missing JSON data'}), 400
        
        id_token = request.json.get('idToken')
        if not id_token:
            return jsonify({'success': False, 'error': 'Missing ID token'}), 400
        
        decoded_token = auth.verify_id_token(id_token, clock_skew_seconds=5)
        user_id = decoded_token['uid']
        session['user_id'] = user_id
        return jsonify({'success': True, 'redirect': url_for('index')})
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
    try:
        user_id = session['user_id']
        print(f"Fetching tasks for user: {user_id}")
        
        # Get tasks reference and notes reference
        tasks_ref = db.collection('tasks').where('user_id', '==', user_id)
        notes_ref = db.collection('notes').where('user_id', '==', user_id)
        
        try:
            # Fetch tasks with ordering
            tasks = []
            for doc in tasks_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream():
                task = doc.to_dict()
                task['id'] = doc.id
                # Format the date
                if 'created_at' in task:
                    task['formatted_date'] = task['created_at'].strftime('%b. %-d')
                tasks.append(task)
            
            # Fetch notes
            notes = []
            for doc in notes_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream():
                note = doc.to_dict()
                note['id'] = doc.id
                if 'created_at' in note:
                    note['formatted_date'] = note['created_at'].strftime('%b. %-d')
                notes.append(note)
            
        except Exception as order_error:
            print(f"Error with ordered query: {str(order_error)}")
            print("Falling back to unordered query")
            
            # Fallback: fetch without ordering if index doesn't exist
            tasks = []
            for doc in tasks_ref.stream():
                task = doc.to_dict()
                task['id'] = doc.id
                tasks.append(task)
            
            # Sort in memory as a temporary solution
            tasks.sort(key=lambda x: x.get('created_at', 0), reverse=True)
            print(f"Successfully fetched {len(tasks)} tasks (unordered)")
            
            # Fallback handling for notes
            notes = []
            for doc in notes_ref.stream():
                note = doc.to_dict()
                note['id'] = doc.id
                notes.append(note)
            
            # Sort in memory as a temporary solution
            notes.sort(key=lambda x: x.get('created_at', 0), reverse=True)
            print(f"Successfully fetched {len(notes)} notes (unordered)")
        
        return render_template('index.html', tasks=tasks, notes=notes)
        
    except Exception as e:
        print(f"Error in index route: {str(e)}")
        return render_template('index.html', tasks=[], notes=[], error="Unable to fetch data. Please try again later.")

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    user_id = session['user_id']
    title = request.form.get('title', 'New Task')
    
    task = {
        'title': title,
        'completed': False,
        'created_at': datetime.now(),
        'user_id': user_id
    }
    db.collection('tasks').add(task)
    return redirect(url_for('index'))

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    user_id = session['user_id']
    title = request.form.get('title', 'New Note')
    content = request.form.get('content', '')
    
    note = {
        'title': title,
        'content': content,
        'created_at': datetime.now(),
        'user_id': user_id
    }
    db.collection('notes').add(note)
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

@app.route('/search', methods=['GET'])
@login_required
def search():
    query = request.args.get('q', '').lower()
    user_id = session['user_id']
    
    try:
        # Get all tasks and notes for the user
        tasks_ref = db.collection('tasks').where('user_id', '==', user_id).stream()
        notes_ref = db.collection('notes').where('user_id', '==', user_id).stream()
        
        # Filter tasks and notes based on search query
        tasks = []
        for doc in tasks_ref:
            task = doc.to_dict()
            if query in task.get('title', '').lower():
                task['id'] = doc.id
                tasks.append(task)
        
        notes = []
        for doc in notes_ref:
            note = doc.to_dict()
            if query in note.get('title', '').lower() or query in note.get('content', '').lower():
                note['id'] = doc.id
                notes.append(note)
        
        return jsonify({
            'tasks': tasks,
            'notes': notes
        })
    except Exception as e:
        print(f"Search error: {str(e)}")
        return jsonify({'error': 'Search failed'}), 500

@app.errorhandler(Exception)
def handle_error(error):
    print(f"Error occurred: {str(error)}")
    return jsonify({
        'success': False,
        'error': str(error)
    }), 500

if __name__ == '__main__':
    app.run(debug=True) 