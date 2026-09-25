import base64
import math
import os
import random
import smtplib
import sqlite3
import time
import requests
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from agora_token_builder import RtcTokenBuilder
from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for, render_template_string
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# 1. Initialize the App exactly ONCE
app = Flask(__name__)

# 2. Apply configurations to this single app instance
CORS(app)
app.secret_key = 'qZ822118@@' 

# 3. Initialize the AI Brain
ai_analyzer = SentimentIntensityAnalyzer()

# ==========================================
# PERSISTENT STORAGE SETUP
# ==========================================
if os.path.exists('/var/data'):
    BASE_DIR = '/var/data'
else:
    BASE_DIR = os.path.dirname(__file__)

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

DB_PATH = os.path.join(BASE_DIR, 'coffee_sparks.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 999
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            real_name TEXT NOT NULL,
            nickname TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            coffee_shop TEXT,
            bio TEXT,
            profile_image TEXT,
            caffeine_status TEXT DEFAULT 'Craving an iced latte ☕',
            audio_intro TEXT,
            last_lat REAL,
            last_lng REAL,
            kyc_status TEXT DEFAULT 'Unverified',
            kyc_image TEXT
        )
    ''')

    migration_cols = [
        ('caffeine_status', "TEXT DEFAULT 'Craving an iced latte ☕'"),
        ('audio_intro', 'TEXT'),
        ('last_lat', 'REAL'),
        ('last_lng', 'REAL'),
        ('kyc_status', "TEXT DEFAULT 'Unverified'"),
        ('kyc_image', 'TEXT'),
        ('sq_teacher', 'TEXT'),
        ('sq_dog', 'TEXT'),
        ('sq_food', 'TEXT'),
        ('sq_phone', 'TEXT'),
        ('sq_date', 'TEXT'),
        ('last_active', 'TEXT')
    ]
    for col, col_type in migration_cols:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # 2. User Photos Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            image_filename TEXT NOT NULL,
            caption TEXT,
            is_private INTEGER DEFAULT 1,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # 3. User Likes Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_user_id, to_user_id),
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')

    # 4. Date Invites Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS date_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            cafe_name TEXT NOT NULL,
            meet_time TEXT NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')

    # 5. Private Moments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_moments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            image_base64 TEXT,
            caption TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 6. Messages Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(from_user_id) REFERENCES users(id),
            FOREIGN KEY(to_user_id) REFERENCES users(id)
        )
    ''')

    # 7. Secret Access Permissions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS secret_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            viewer_id INTEGER NOT NULL,
            moment_id INTEGER NOT NULL,
            UNIQUE(owner_id, viewer_id, moment_id)
        )
    ''')

    # 8. Profile Wall Comments Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS profile_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_user_id INTEGER NOT NULL,
            commenter_user_id INTEGER NOT NULL,
            commenter_name TEXT NOT NULL,
            commenter_image TEXT,
            comment TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(profile_user_id) REFERENCES users(id),
            FOREIGN KEY(commenter_user_id) REFERENCES users(id)
        )
    ''')

    # 9. OTP Verification Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at DATETIME NOT NULL
        )
    ''')

    # 10. Dating Preferences
    pref_cols = [
        ('pref_age_min', 'INTEGER DEFAULT 18'),
        ('pref_age_max', 'INTEGER DEFAULT 85'),
        ('pref_genders', 'TEXT'),
        ('pref_builds', 'TEXT'),
        ('pref_habits', 'TEXT'),
        ('pref_beliefs', 'TEXT'),
        ('pref_backgrounds', 'TEXT')
    ]
    for col, col_type in pref_cols:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
        except sqlite3.OperationalError:
            pass

    # 11. Blocked Users Table (Google Play)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(blocker_id, blocked_id)
        )
    ''')

    # 12. Reported Users Table (Google Play)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reported_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            reported_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

setup_database()

# ==========================================
# API ENDPOINTS
# ==========================================

AGORA_APP_ID = "c03d6118308348ba96a6b8a3d5484487"
AGORA_APP_CERT = "280aa0b50d4144ef9ae2f096bb14be0b"

@app.route('/get_agora_token', methods=['GET'])
def get_agora_token():
    channel_name = request.args.get('channel_name')
    uid = request.args.get('uid', default=0, type=int)
    if not channel_name:
        return jsonify({"error": "channel_name is required"}), 400
    role = 1 
    privilege_expired_ts = int(time.time()) + 7200
    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, AGORA_APP_CERT, channel_name, uid, role, privilege_expired_ts
    )
    return jsonify({"status": "success", "token": token, "channel_name": channel_name}), 200

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "success", "message": "Coffee Sparks server is awake!"})

@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    code = str(random.randint(100000, 999999))
    expires_at_str = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM otp_codes WHERE email = ?', (email,))
        conn.execute('''
            INSERT INTO otp_codes (email, code, expires_at)
            VALUES (?, ?, ?)
        ''', (email, code, expires_at_str))
        conn.commit()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database error: {str(e)}"}), 500
    finally:
        conn.close()

    BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
    if not BREVO_API_KEY:
        render_secret_path = "/etc/secrets/brevo_key.txt"
        local_secret_path = "brevo_key.txt"
        target_path = render_secret_path if os.path.exists(render_secret_path) else local_secret_path
        try:
            with open(target_path, "r") as key_file:
                BREVO_API_KEY = key_file.read().strip()
        except FileNotFoundError:
            print("[Notice] Secret file 'brevo_key.txt' not found.")

    SENDER_EMAIL = "contact@driveelite.ph"

    if not BREVO_API_KEY:
        print(f"[OTP LOG FALLBACK] Email: {email} | Code: {code}")
        return jsonify({"status": "success", "message": "OTP Sent (Fallback)!"}), 200

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "sender": {"name": "Let's Have Coffee", "email": SENDER_EMAIL},
                "to": [{"email": email}],
                "subject": "Your LHC Login Code ☕",
                "textContent": f"Your Let's Have Coffee login code is: {code}\n\nIt expires in 5 minutes. ☕"
            },
            timeout=10
        )
        if response.status_code in [200, 201]:
            return jsonify({"status": "success", "message": "OTP Sent to your Inbox!"}), 200
        else:
            print(f"[OTP LOG FALLBACK] Email: {email} | Code: {code}")
            return jsonify({"status": "success", "message": "OTP Sent (Fallback)!"}), 200
    except Exception as e:
        print(f"[OTP LOG FALLBACK] Email: {email} | Code: {code}")
        return jsonify({"status": "success", "message": "OTP Sent (Fallback)!"}), 200

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()

    conn = get_db_connection()
    otp_record = conn.execute('SELECT * FROM otp_codes WHERE email = ? AND code = ?', (email, code)).fetchone()

    if not otp_record:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid code. Try again."}), 400

    expires_at = datetime.strptime(otp_record['expires_at'], "%Y-%m-%d %H:%M:%S")
    if expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        conn.close()
        return jsonify({"status": "error", "message": "Code expired. Request a new one."}), 400

    conn.execute('DELETE FROM otp_codes WHERE email = ?', (email,))
    user = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
    conn.commit()
    conn.close()

    if user:
        return jsonify({"status": "success", "is_new_user": False, "user_id": user['id']}), 200
    else:
        return jsonify({"status": "success", "is_new_user": True}), 200

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    lat = data.get('lat')
    lng = data.get('lng')

    if not email or not password:
        return jsonify({"status": "error", "message": "Missing credentials"}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    if user and check_password_hash(user['password'], password):
        if lat is not None and lng is not None:
            conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, user['id']))
            conn.commit()
        conn.close()
        return jsonify({"status": "success", "user_id": user['id']}), 200
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid email or password"}), 401

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', f"user_{int(time.time())}@coffee.com").strip().lower()
    raw_password = data.get('password', 'temporarypassword')
    hashed_password = generate_password_hash(raw_password)
    real_name = data.get('real_name', 'Coffee Lover')
    nickname = data.get('nickname', real_name)
    age = int(data.get('age', 18))
    gender = data.get('gender', 'Man')
    coffee_shop = data.get('coffee_shop', 'Local Cafe')
    bio = data.get('bio', '')

    sq_teacher = data.get('sq_teacher', '').strip().lower()
    sq_dog = data.get('sq_dog', '').strip().lower()
    sq_food = data.get('sq_food', '').strip().lower()
    sq_phone = data.get('sq_phone', '').strip().lower()
    sq_date = data.get('sq_date', '').strip().lower()

    avatar_filename = None
    image_b64 = data.get('image_base64')
    if image_b64:
        try:
            avatar_filename = f"avatar_{int(time.time())}.jpg"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], avatar_filename)
            with open(filepath, "wb") as fh:
                fh.write(base64.b64decode(image_b64))
        except Exception as err:
            print(f"Error saving avatar: {err}")
            avatar_filename = None

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (email, password, real_name, nickname, age, gender, coffee_shop, bio, profile_image, sq_teacher, sq_dog, sq_food, sq_phone, sq_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (email, hashed_password, real_name, nickname, age, gender, coffee_shop, bio, avatar_filename, sq_teacher, sq_dog, sq_food, sq_phone, sq_date))
        conn.commit()
        new_user_id = cursor.lastrowid
        return jsonify({"status": "success", "message": "Profile registered!", "user_id": new_user_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "message": "Email already exists."}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/update_preferences', methods=['POST'])
def update_preferences():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "Missing user ID"}), 400

    age_min = data.get('age_min', 18)
    age_max = data.get('age_max', 85)
    genders = ",".join(data.get('genders', []))
    builds = ",".join(data.get('builds', []))
    habits = ",".join(data.get('habits', []))
    beliefs = ",".join(data.get('beliefs', []))
    backgrounds = ",".join(data.get('backgrounds', []))

    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE users SET
            pref_age_min = ?, pref_age_max = ?, pref_genders = ?,
            pref_builds = ?, pref_habits = ?, pref_beliefs = ?, pref_backgrounds = ?
            WHERE id = ?
        ''', (age_min, age_max, genders, builds, habits, beliefs, backgrounds, user_id))
        conn.commit()
        return jsonify({"status": "success", "message": "Preferences updated!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/submit_kyc', methods=['POST'])
def submit_kyc():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    image_b64 = data.get('image_base64')

    if not user_id or not image_b64:
        return jsonify({"status": "error", "message": "Missing user ID or image"}), 400

    filename = secure_filename(f"kyc_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_b64))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error saving KYC photo: {e}"}), 500

    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET kyc_status = ?, kyc_image = ? WHERE id = ?', ('Pending', filename, user_id))
        conn.commit()
        return jsonify({"status": "success", "message": "KYC submitted successfully! Pending review."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/recover_account', methods=['POST'])
def recover_account():
    data = request.get_json(force=True, silent=True) or {}
    recovery_type = data.get('type')
    ans_teacher = data.get('sq_teacher')
    ans_dog = data.get('sq_dog')
    ans_food = data.get('sq_food')
    ans_phone = data.get('sq_phone')
    ans_date = data.get('sq_date')

    conn = get_db_connection()
    try:
        if recovery_type == 'email':
            nickname = data.get('nickname', '').strip()
            query = "SELECT email FROM users WHERE nickname = ?"
            params = [nickname]

            if ans_teacher is not None:
                query += " AND sq_teacher = ?"; params.append(ans_teacher.strip().lower())
            if ans_dog is not None:
                query += " AND sq_dog = ?"; params.append(ans_dog.strip().lower())
            if ans_food is not None:
                query += " AND sq_food = ?"; params.append(ans_food.strip().lower())
            if ans_phone is not None:
                query += " AND sq_phone = ?"; params.append(ans_phone.strip().lower())
            if ans_date is not None:
                query += " AND sq_date = ?"; params.append(ans_date.strip().lower())

            user = conn.execute(query, params).fetchone()
            if user:
                return jsonify({"status": "success", "message": f"Your email is: {user['email']}"}), 200
            return jsonify({"status": "error", "message": "Answers do not match any records."}), 404

        elif recovery_type == 'password':
            email = data.get('email', '').strip().lower()
            new_password = data.get('new_password', '').strip()
            query = "SELECT id FROM users WHERE email = ?"
            params = [email]

            if ans_teacher is not None:
                query += " AND sq_teacher = ?"; params.append(ans_teacher.strip().lower())
            if ans_dog is not None:
                query += " AND sq_dog = ?"; params.append(ans_dog.strip().lower())
            if ans_food is not None:
                query += " AND sq_food = ?"; params.append(ans_food.strip().lower())
            if ans_phone is not None:
                query += " AND sq_phone = ?"; params.append(ans_phone.strip().lower())
            if ans_date is not None:
                query += " AND sq_date = ?"; params.append(ans_date.strip().lower())

            user = conn.execute(query, params).fetchone()
            if user:
                hashed_pw = generate_password_hash(new_password)
                conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed_pw, user['id']))
                conn.commit()
                return jsonify({"status": "success", "message": "Password successfully reset! You can now log in."}), 200

            return jsonify({"status": "error", "message": "Answers do not match our records for that email."}), 404
        return jsonify({"status": "error", "message": "Invalid request type"}), 400
    finally:
        conn.close()

@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    if lat is not None and lng is not None:
        conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, current_user_id))
        conn.commit()

    prefs = conn.execute('SELECT pref_age_min, pref_age_max, pref_genders, coffee_shop FROM users WHERE id = ?', (current_user_id,)).fetchone()
    age_min = prefs['pref_age_min'] if prefs and prefs['pref_age_min'] else 18
    age_max = prefs['pref_age_max'] if prefs and prefs['pref_age_max'] else 85
    user_shop = prefs['coffee_shop'] if prefs and prefs['coffee_shop'] else ""

    query = '''
        SELECT id, nickname, age, gender, coffee_shop, bio, profile_image, caffeine_status, last_lat, last_lng, last_active
        FROM users 
        WHERE id != ? AND age >= ? AND age <= ?
    '''
    params = [current_user_id, age_min, age_max]

    cursor = conn.cursor()
    potential_matches = cursor.execute(query, params).fetchall()
    conn.close()

    feed_list = []
    for u in potential_matches:
        u_lat = u['last_lat']
        u_lng = u['last_lng']
        if lat is not None and lng is not None and u_lat is not None and u_lng is not None:
            distance = haversine_distance(lat, lng, u_lat, u_lng)
        else:
            distance = 1.2 

        avatar = u['profile_image']
        img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"
        
        is_coffee_match = user_shop and u['coffee_shop'] and user_shop.strip().lower() == u['coffee_shop'].strip().lower()
        tag_title = "☕ Shared Coffee Vibe" if is_coffee_match else (u['coffee_shop'] or "Local Cafe")

        last_active_str = u['last_active']
        is_online = False
        if last_active_str:
            try:
                last_act_dt = datetime.strptime(last_active_str, "%Y-%m-%d %H:%M:%S")
                if datetime.utcnow() - last_act_dt < timedelta(minutes=5):
                    is_online = True
            except Exception:
                pass

        safe_lat = round(u_lat, 3) if u_lat is not None else None
        safe_lng = round(u_lng, 3) if u_lng is not None else None

        feed_list.append({
            "id": u["id"],
            "name": u["nickname"] or "Anonymous",
            "age": str(u["age"] or 25),
            "shop": u["coffee_shop"] or "Local Cafe",
            "bio": u["bio"] or "Looking for good coffee and great conversation!",
            "image": img_url,
            "tags": ["Coffee Lover", tag_title, u["caffeine_status"] or "Craving Latte"],
            "distance_km": round(distance, 1),
            "is_online": is_online,
            "lat": safe_lat, 
            "lng": safe_lng  
        })
        
    feed_list.sort(key=lambda x: x['distance_km'])
    return jsonify({"status": "success", "feed": feed_list}), 200

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    user_id = data.get('user_id')
    if user_id:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        conn.execute('UPDATE users SET last_active = ? WHERE id = ?', (now_str, user_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    return jsonify({"error": "Missing user_id"}), 400

@app.route('/user_profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    avatar = user['profile_image']
    img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"

    last_active_str = user['last_active'] if 'last_active' in user.keys() else None
    is_online = False
    if last_active_str:
        try:
            last_act_dt = datetime.strptime(last_active_str, "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - last_act_dt < timedelta(minutes=5):
                is_online = True
        except Exception:
            pass

    return jsonify({
        "status": "success",
        "user": {
            "id": user["id"],
            "nickname": user["nickname"],
            "age": user["age"],
            "coffee_shop": user["coffee_shop"],
            "bio": user["bio"],
            "image": img_url,
            "caffeine_status": user["caffeine_status"] if "caffeine_status" in user.keys() else "Chilling",
            "kyc_status": user["kyc_status"] if "kyc_status" in user.keys() else "Unverified",
            "is_premium": bool(user["is_premium"]) if "is_premium" in user.keys() else False,
            "is_online": is_online
        }
    }), 200

@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id', 1)
    image_b64 = data.get('image_base64')

    if not image_b64:
        return jsonify({"status": "error", "message": "No image uploaded"}), 400

    filename = secure_filename(f"avatar_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_b64))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error saving photo: {e}"}), 500

    conn = get_db_connection()
    conn.execute('UPDATE users SET profile_image = ? WHERE id = ?', (filename, user_id))
    conn.commit()
    conn.close()

    return jsonify({"status": "success", "avatar_url": f"{request.host_url}uploads/{filename}"}), 200

@app.route('/user_stats/<int:user_id>', methods=['GET'])
def get_user_stats(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    user = cursor.execute('SELECT coffee_shop FROM users WHERE id = ?', (user_id,)).fetchone()
    current_shop = user['coffee_shop'] if user else ""

    vibes_count = cursor.execute('SELECT COUNT(*) as count FROM users WHERE LOWER(coffee_shop) = LOWER(?) AND id != ?', (current_shop, user_id)).fetchone()['count']
    likes_count = cursor.execute('SELECT COUNT(*) as count FROM user_likes WHERE to_user_id = ?', (user_id,)).fetchone()['count']

    match_count = cursor.execute('''
        SELECT COUNT(*) as count FROM user_likes a
        JOIN user_likes b ON a.to_user_id = b.from_user_id AND a.from_user_id = b.to_user_id
        WHERE a.from_user_id = ?
    ''', (user_id,)).fetchone()['count']
    conn.close()

    return jsonify({"status": "success", "match_brew": match_count, "similar_vibes": vibes_count, "local_likes": likes_count}), 200

@app.route('/insight_details/<category>/<int:user_id>', methods=['GET'])
def get_insight_details(category, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    current_user = cursor.execute('SELECT coffee_shop FROM users WHERE id = ?', (user_id,)).fetchone()
    current_shop = current_user['coffee_shop'] if current_user else ""
    users_list = []

    if category == 'similar_vibes':
        rows = cursor.execute('SELECT id, nickname, age, coffee_shop, bio, profile_image FROM users WHERE LOWER(coffee_shop) = LOWER(?) AND id != ?', (current_shop, user_id)).fetchall()
        title = f"Similar Coffee Vibes ({current_shop})"
    elif category == 'local_likes':
        rows = cursor.execute('SELECT u.id, u.nickname, u.age, u.coffee_shop, u.bio, u.profile_image FROM users u JOIN user_likes l ON u.id = l.from_user_id WHERE l.to_user_id = ?', (user_id,)).fetchall()
        title = "Local Coffee Likes"
    elif category == 'match_brew':
        rows = cursor.execute('''
            SELECT u.id, u.nickname, u.age, u.coffee_shop, u.bio, u.profile_image 
            FROM users u 
            JOIN user_likes a ON u.id = a.to_user_id 
            JOIN user_likes b ON a.from_user_id = b.to_user_id AND a.to_user_id = b.from_user_id 
            WHERE a.from_user_id = ?
        ''', (user_id,)).fetchall()
        title = "Match Brew (Mutual Sparks)"
    else:
        conn.close()
        return jsonify({"status": "error", "message": "Unknown category"}), 400

    conn.close()
    for r in rows:
        avatar = r['profile_image']
        img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80"
        users_list.append({
            "id": r["id"],
            "name": r["nickname"] or "Coffee Lover",
            "age": str(r["age"] or ""),
            "shop": r["coffee_shop"] or "Local Spot",
            "bio": r["bio"] or "Looking for great coffee & conversation!",
            "image": img_url
        })

    return jsonify({"status": "success", "title": title, "users": users_list}), 200

@app.route('/upload_private_moment', methods=['POST'])
def upload_private_moment():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    image_base64 = data.get('image_base64')
    caption = data.get('caption', '')

    if not user_id or not image_base64:
        return jsonify({"status": "error", "message": "Missing user_id or image"}), 400

    filename = secure_filename(f"moment_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        with open(filepath, "wb") as fh:
            fh.write(base64.b64decode(image_base64))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error saving file: {e}"}), 500

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO private_moments (user_id, image_base64, caption) VALUES (?, ?, ?)',
                     (user_id, filename, caption))
        conn.commit()
        return jsonify({"status": "success", "message": "Private moment saved successfully!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/get_secret_moments/<int:viewer_id>/<int:target_id>', methods=['GET'])
def get_secret_moments(viewer_id, target_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT id, image_base64, caption, timestamp FROM private_moments WHERE user_id = ? ORDER BY id DESC', (target_id,)).fetchall()

    moments = []
    for r in rows:
        moment_id = r['id']
        filename = r['image_base64'] or ''
        img_url = f"{request.host_url}uploads/{filename}" if filename else ""

        unlocked = True
        if viewer_id != target_id:
            access = conn.execute('''
                SELECT 1 FROM secret_access WHERE owner_id = ? AND viewer_id = ? AND moment_id = ?
            ''', (target_id, viewer_id, moment_id)).fetchone()
            unlocked = access is not None

        moments.append({
            "id": moment_id,
            "image": img_url,
            "caption": r['caption'] or "",
            "unlocked": unlocked,
            "timestamp": r['timestamp']
        })

    conn.close()
    return jsonify({"status": "success", "moments": moments}), 200

@app.route('/grant_secret_access', methods=['POST'])
def grant_secret_access():
    data = request.get_json(force=True, silent=True) or {}
    owner_id = data.get('owner_id')
    viewer_id = data.get('viewer_id')
    moment_id = data.get('moment_id')

    if not owner_id or not viewer_id or not moment_id:
        return jsonify({"status": "error", "message": "Missing IDs"}), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO secret_access (owner_id, viewer_id, moment_id)
            VALUES (?, ?, ?)
        ''', (owner_id, viewer_id, moment_id))
        conn.commit()
        return jsonify({"status": "success", "message": "Access granted!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/delete_private_moment/<int:moment_id>', methods=['DELETE'])
def delete_private_moment(moment_id):
    conn = get_db_connection()
    row = conn.execute('SELECT image_base64 FROM private_moments WHERE id = ?', (moment_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Moment not found"}), 404

    filename = row['image_base64']
    if filename:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                print(f"Error deleting file: {e}")

    conn.execute('DELETE FROM private_moments WHERE id = ?', (moment_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Secret moment deleted successfully!"}), 200

@app.route('/unread_count/<int:user_id>', methods=['GET'])
def get_unread_count(user_id):
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT COUNT(*) as unread FROM messages WHERE to_user_id = ? AND is_read = 0",
        (user_id,)
    ).fetchone()
    conn.close()
    return jsonify({"status": "success", "unread": row['unread'] if row else 0}), 200

@app.route('/mark_read/<int:user_id>/<int:sender_id>', methods=['POST'])
def mark_read(user_id, sender_id):
    conn = get_db_connection()
    conn.execute(
        "UPDATE messages SET is_read = 1 WHERE to_user_id = ? AND from_user_id = ?",
        (user_id, sender_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "success"}), 200

@app.route('/get_messages/<int:user1>/<int:user2>', methods=['GET'])
def get_messages(user1, user2):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    rows = cursor.execute('''
        SELECT from_user_id, content 
        FROM messages 
        WHERE (from_user_id = ? AND to_user_id = ?) 
           OR (from_user_id = ? AND to_user_id = ?)
        ORDER BY id ASC
    ''', (user1, user2, user2, user1)).fetchall()
    conn.close()

    messages = [{"sender": r['from_user_id'], "text": r['content']} for r in rows]
    
    spark_level = 0.15 
    for msg in messages:
        text = msg['text']
        sentiment = ai_analyzer.polarity_scores(text)
        vibe = sentiment['compound'] 
        
        if vibe > 0.3:
            spark_level += 0.08
        elif vibe > 0.0:
            spark_level += 0.03
        elif vibe < -0.1:
            spark_level -= 0.10
        elif len(text.strip()) < 4:
            spark_level -= 0.05
            
        spark_level = max(0.0, min(1.0, spark_level))

    return jsonify({
        "status": "success", 
        "messages": messages, 
        "spark_level": spark_level
    }), 200

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json(force=True, silent=True) or {}
    from_id = data.get('from_user_id')
    to_id = data.get('to_user_id')
    content = data.get('content', '')

    if not from_id or not to_id or not content:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO messages (from_user_id, to_user_id, content)
            VALUES (?, ?, ?)
        ''', (from_id, to_id, content))
        conn.commit()
        return jsonify({"status": "success", "message": "Message sent!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/create_date_invite', methods=['POST'])
def create_date_invite():
    data = request.get_json(force=True, silent=True) or {}
    from_user_id = data.get('from_user_id')
    to_user_id = data.get('to_user_id')
    cafe_name = data.get('cafe_name', 'Local Cafe')
    meet_time = data.get('meet_time', 'Tomorrow morning')
    message = data.get('message', '')

    if not from_user_id or not to_user_id:
        return jsonify({"status": "error", "message": "Missing sender or receiver IDs"}), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO date_invites (from_user_id, to_user_id, cafe_name, meet_time, message, status)
            VALUES (?, ?, ?, ?, ?, 'Pending')
        ''', (from_user_id, to_user_id, cafe_name, meet_time, message))
        
        conn.execute('INSERT OR IGNORE INTO user_likes (from_user_id, to_user_id) VALUES (?, ?)', (from_user_id, to_user_id))
        conn.execute('INSERT OR IGNORE INTO user_likes (from_user_id, to_user_id) VALUES (?, ?)', (to_user_id, from_user_id))
        
        conn.commit()
        return jsonify({"status": "success", "message": "Spark sent & instantly matched!"}), 201
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/post_comment', methods=['POST'])
def post_comment():
    data = request.get_json(force=True, silent=True) or {}
    profile_id = data.get('profile_user_id')
    commenter_id = data.get('commenter_user_id')
    commenter_name = data.get('commenter_name', 'Coffee Passersby')
    commenter_image = data.get('commenter_image', '')
    text = data.get('comment', '').strip()

    if not profile_id or not commenter_id or not text:
        return jsonify({"status": "error", "message": "Missing fields"}), 400

    lower_text = text.lower()
    negative_words = ['ugly', 'hate', 'bad', 'horrible', 'stupid', 'loser', 'trash', 'scam']
    if any(word in lower_text for word in negative_words):
        return jsonify({
            "status": "error",
            "message": "Public wall keeps good vibes only! Save the spicy banter for private chat rooms ☕"
        }), 400

    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO profile_comments (profile_user_id, commenter_user_id, commenter_name, commenter_image, comment)
            VALUES (?, ?, ?, ?, ?)
        ''', (profile_id, commenter_id, commenter_name, commenter_image, text))
        conn.commit()
        return jsonify({"status": "success", "message": "Comment posted!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/get_comments/<int:profile_user_id>', methods=['GET'])
def get_comments(profile_user_id):
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT id, commenter_user_id, commenter_name, commenter_image, comment, timestamp
        FROM profile_comments
        WHERE profile_user_id = ?
        ORDER BY id DESC
    ''', (profile_user_id,)).fetchall()
    conn.close()

    comments = []
    for r in rows:
        comments.append({
            "id": r['id'],
            "commenter_id": r['commenter_user_id'],
            "name": r['commenter_name'],
            "image": r['commenter_image'],
            "comment": r['comment'],
            "timestamp": r['timestamp']
        })
    return jsonify({"status": "success", "comments": comments}), 200

@app.route('/delete_user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM user_likes WHERE from_user_id = ? OR to_user_id = ?', (user_id, user_id))
        conn.execute('DELETE FROM private_moments WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM profile_comments WHERE profile_user_id = ? OR commenter_user_id = ?', (user_id, user_id))
        conn.execute('DELETE FROM messages WHERE from_user_id = ? OR to_user_id = ?', (user_id, user_id))
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        return jsonify({"status": "success", "message": "Account deleted successfully!"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/upgrade_premium', methods=['POST'])
def upgrade_premium():
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"status": "error", "message": "Missing user ID"}), 400

    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET is_premium = 1 WHERE id = ?', (user_id,))
        conn.commit()
        return jsonify({"status": "success", "message": "Welcome to LHC Gold Roaster Club! ☕"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


# ==========================================
# GOOGLE PLAY COMPLIANCE ROUTES
# ==========================================
@app.route('/block_user', methods=['POST'])
def block_user():
    data = request.get_json(force=True, silent=True) or {}
    blocker_id = data.get('blocker_id')
    blocked_id = data.get('blocked_id')

    if not blocker_id or not blocked_id:
        return jsonify({"status": "error", "message": "Missing IDs"}), 400

    conn = get_db_connection()
    try:
        conn.execute('INSERT OR IGNORE INTO blocked_users (blocker_id, blocked_id) VALUES (?, ?)', (blocker_id, blocked_id))
        conn.execute('DELETE FROM user_likes WHERE (from_user_id = ? AND to_user_id = ?) OR (from_user_id = ? AND to_user_id = ?)', 
                     (blocker_id, blocked_id, blocked_id, blocker_id))
        conn.commit()
        return jsonify({"status": "success", "message": "User blocked successfully."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/report_user', methods=['POST'])
def report_user():
    data = request.get_json(force=True, silent=True) or {}
    reporter_id = data.get('reporter_id')
    reported_id = data.get('reported_id')
    reason = data.get('reason', 'Inappropriate behavior')

    if not reporter_id or not reported_id:
        return jsonify({"status": "error", "message": "Missing IDs"}), 400

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO reported_users (reporter_id, reported_id, reason) VALUES (?, ?, ?)', (reporter_id, reported_id, reason))
        conn.commit()
        return jsonify({"status": "success", "message": "Report submitted to admin for review."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


# ==========================================
# PUBLIC LANDING PAGE & COMPLIANCE
# ==========================================

LANDING_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Let's Have Coffee | Meet, Match & Brew</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #1C0F0A; color: white; margin: 0; padding: 0; line-height: 1.6; }
        .hero { text-align: center; padding: 80px 20px; background: linear-gradient(180deg, #2C1810 0%, #1C0F0A 100%); border-bottom: 1px solid #3A2520; }
        .hero h1 { color: #D6AD70; font-size: 3rem; margin-bottom: 10px; }
        .hero p { font-size: 1.2rem; color: #CCC; max-width: 600px; margin: 0 auto 30px auto; }
        .btn-download { display: inline-block; background: #D6AD70; color: black; padding: 15px 30px; font-size: 1.2rem; font-weight: bold; text-decoration: none; border-radius: 30px; box-shadow: 0 4px 15px rgba(214, 173, 112, 0.3); transition: transform 0.2s; }
        .btn-download:hover { transform: translateY(-2px); }
        .section { max-width: 1000px; margin: 0 auto; padding: 60px 20px; }
        .section h2 { color: #D6AD70; text-align: center; font-size: 2rem; margin-bottom: 40px; }
        .features { display: flex; flex-wrap: wrap; gap: 30px; justify-content: center; }
        .feature-card { background: #2C1810; padding: 30px; border-radius: 16px; flex: 1; min-width: 250px; text-align: center; border: 1px solid #3A2520; }
        .feature-card h3 { color: white; margin-top: 0; }
        .faq { max-width: 700px; margin: 0 auto; background: #2C1810; padding: 30px; border-radius: 16px; border: 1px solid #3A2520; }
        .faq h4 { color: #D6AD70; margin-bottom: 5px; }
        .faq p { color: #AAA; margin-top: 0; margin-bottom: 20px; }
        .footer { text-align: center; padding: 40px 20px; border-top: 1px solid #3A2520; margin-top: 40px; font-size: 0.9rem; color: #888; }
        .footer a { color: #D6AD70; text-decoration: none; margin: 0 10px; }
    </style>
</head>
<body>
    <div class="hero">
        <h1>Let's Have Coffee ☕</h1>
        <p>Skip the endless swiping. Match with local coffee lovers, vibe check with our AI Spark Meter, and meet up for a real connection.</p>
        <a href="/download-apk" class="btn-download">Download APK for Android</a>
    </div>
    <div class="section">
        <h2>Why Join The Club?</h2>
        <div class="features">
            <div class="feature-card">
                <h3>⚡ AI Spark Meter</h3>
                <p>Our intelligent chat meter physically rises and falls based on the vibe of your conversation. No more guessing if they are interested.</p>
            </div>
            <div class="feature-card">
                <h3>📍 Local Matches</h3>
                <p>Filter connections by your favorite local coffee shops. Match with people who already love your daily spot.</p>
            </div>
            <div class="feature-card">
                <h3>🛡️ Verified Safe</h3>
                <p>Strict 18+ entry, optional government ID KYC verification, and built-in video dating to ensure the person you meet is real.</p>
            </div>
        </div>
    </div>
    <div class="section">
        <h2>Help & FAQ</h2>
        <div class="faq">
            <h4>How do I install the APK?</h4>
            <p>Download the file using the button above. Open your phone's Settings > Security, and enable "Install from Unknown Sources", then tap the downloaded file.</p>
            <h4>Is the app free to use?</h4>
            <p>Yes! Matching and chatting are completely free. Premium features like unlimited Virtual Video Dates are available for a small upgrade.</p>
            <h4>How do I report a bad interaction?</h4>
            <p>Tap the three-dot menu in the top right of any chat or profile to instantly report or block a user. Our admin team reviews all reports within 24 hours.</p>
        </div>
    </div>
    <div class="footer">
        <p>&copy; 2026 Let's Have Coffee. All rights reserved.</p>
        <div>
            <a href="/privacy">Privacy Policy</a> | 
            <a href="/terms">Terms of Service</a> | 
            <a href="mailto:support@letshavecoffee.com">Contact Support</a>
        </div>
    </div>
</body>
</html>
"""

PRIVACY_POLICY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Privacy Policy | Let's Have Coffee</title>
    <style>
        body { font-family: Arial, sans-serif; background: #1C0F0A; color: #CCC; max-width: 800px; margin: 0 auto; padding: 40px 20px; line-height: 1.6; }
        h1, h2 { color: #D6AD70; }
        a { color: #D6AD70; text-decoration: none; }
    </style>
</head>
<body>
    <a href="/">&larr; Back to Home</a>
    <h1>Privacy Policy</h1>
    <p>Last updated: October 2026</p>
    <h2>1. Information We Collect</h2>
    <p>We collect information you provide directly to us during registration, including your email, age (must be 18+), gender preferences, location data (when actively using the radar feature), and profile images.</p>
    <h2>2. User-Generated Content (UGC)</h2>
    <p>Let's Have Coffee is a social platform. Messages, images, and public comments you post are stored securely on our servers. We maintain a zero-tolerance policy for objectionable content. Users can be blocked or reported directly within the app.</p>
    <h2>3. How We Use Your Data</h2>
    <p>Your location data is used strictly to calculate distance to potential matches and is never shared with third parties. Your chat data is processed by our AI Spark Meter in real-time to generate match compatibility scores.</p>
    <h2>4. Data Deletion</h2>
    <p>You may request full deletion of your account, photos, and chat history at any time by navigating to Settings > Delete Account within the app, or by contacting our support team.</p>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def index():
    return render_template_string(LANDING_PAGE_HTML)

@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template_string(PRIVACY_POLICY_HTML)

@app.route('/terms', methods=['GET'])
def terms():
    return "<h1>Terms of Service</h1><p>By using Let's Have Coffee, you confirm you are 18 years or older and agree to maintain a respectful, safe environment for all users.</p>"

@app.route('/download-apk', methods=['GET'])
def download_apk():
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], 'lhc.apk', as_attachment=True)
    except FileNotFoundError:
        return "The APK file is currently being updated. Please check back later.", 404

# ==========================================
# STANDALONE WEB ADMIN PORTAL
# ==========================================

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>LHC Admin Portal</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background: #1C0F0A; color: white; padding: 20px; }
        .card { background: #2C1810; padding: 20px; border-radius: 12px; border: 1px solid #D6AD70; margin-bottom: 20px; }
        input, button { padding: 10px; margin-top: 10px; border-radius: 8px; border: none; width: 100%; max-width: 300px; display: block;}
        button { background: #D6AD70; font-weight: bold; cursor: pointer; color: black; }
        .danger { background: #B71C1C; color: white; }
    </style>
</head>
<body>
    <h1>☕ Let's Have Coffee - Admin</h1>
    <div class="card">
        <h3>🚀 Application Launch</h3>
        <p>Current Trial End Date: <br><b>{{ trial_end if trial_end else 'App Not Launched Yet' }}</b></p>
        <form action="/admin/action/launch" method="POST">
            <button class="danger" type="submit">Start 30-Day Free Trial For All Users</button>
        </form>
    </div>
    <div class="card">
        <h3>⚙️ Global Parameters</h3>
        <form action="/admin/action/update_params" method="POST">
            <label>Radar Search Radius (km):</label>
            <input type="text" name="radar_radius" value="{{ radar_radius }}">
            <label>Premium Upgrade Price (PHP):</label>
            <input type="text" name="premium_price" value="{{ premium_price }}">
            <button type="submit">Save Parameters</button>
        </form>
    </div>
    <a href="/admin/logout" style="color: #D6AD70; text-decoration: none; font-weight: bold;">Log Out</a>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body{background:#1C0F0A; color:white; font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;}
        .login-box { background: #2C1810; padding: 30px; border-radius: 12px; border: 1px solid #D6AD70; text-align: center; }
        input, button { padding: 12px; margin-top: 15px; border-radius: 8px; border: none; width: 90%; }
        button { background: #D6AD70; font-weight: bold; cursor: pointer; color: black;}
    </style>
</head>
<body>
    <div class="login-box">
        <h2>Admin Login</h2>
        <form action="/admin/login" method="POST">
            <input type="password" name="password" placeholder="Enter Master Password" required>
            <button type="submit">Access Portal</button>
        </form>
    </div>
</body>
</html>
"""

@app.route('/admin', methods=['GET'])
def admin_portal():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS global_config (key TEXT UNIQUE, value TEXT)')
    rows = conn.execute('SELECT * FROM global_config').fetchall()
    config = {r['key']: r['value'] for r in rows}
    conn.close()
    
    return render_template_string(ADMIN_DASHBOARD_HTML, 
                                  trial_end=config.get('trial_end'),
                                  radar_radius=config.get('radar_radius', '1.2'),
                                  premium_price=config.get('premium_price', '499'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == 'qZ822118@@': 
            session['is_admin'] = True
            return redirect(url_for('admin_portal'))
        return "Invalid Password", 401
    return render_template_string(LOGIN_HTML)

@app.route('/admin/action/launch', methods=['POST'])
def admin_action_launch():
    if not session.get('is_admin'): return "Unauthorized", 401
    conn = get_db_connection()
    future_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    conn.execute('INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)', ('trial_end', future_date))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_portal'))

@app.route('/admin/action/update_params', methods=['POST'])
def admin_action_update_params():
    if not session.get('is_admin'): return "Unauthorized", 401
    radar = request.form.get('radar_radius')
    price = request.form.get('premium_price')
    conn = get_db_connection()
    conn.execute('INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)', ('radar_radius', radar))
    conn.execute('INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)', ('premium_price', price))
    conn.commit()
    conn.close()
    return redirect(url_for('admin_portal'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
