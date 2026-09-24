import base64
import math
import os
import random
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
# Put these imports at the very top of app.py
from agora_token_builder import RtcTokenBuilder
import time
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def get_db_connection():
    conn = sqlite3.connect('coffee_sparks.db', check_same_thread=False)
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

    # ADDED 'last_active' to migrations for the Online Status feature!
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
        ('last_active', 'TEXT') # <-- NEW COLUMN FOR ONLINE STATUS
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

    # 5. Private Moments (Secret Brews) Table
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

    # 10. Dating Preferences Columns to Users Table
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

    conn.commit()
    conn.close()


setup_database()

# Put this route with your other endpoints
AGORA_APP_ID = "c03d6118308348ba96a6b8a3d5484487"
AGORA_APP_CERT = "280aa0b50d4144ef9ae2f096bb14be0b"
@app.route('/get_agora_token', methods=['GET'])
def get_agora_token():
    channel_name = request.args.get('channel_name')
    uid = request.args.get('uid', default=0, type=int)
    
    if not channel_name:
        return jsonify({"error": "channel_name is required"}), 400

    # Role 1 is Broadcaster (allows sending and receiving video)
    role = 1 
    # Token valid for 2 hours (7200 seconds)
    privilege_expired_ts = int(time.time()) + 7200

    token = RtcTokenBuilder.buildTokenWithUid(
        AGORA_APP_ID, 
        AGORA_APP_CERT, 
        channel_name, 
        uid, 
        role, 
        privilege_expired_ts
    )
    
    return jsonify({"status": "success", "token": token, "channel_name": channel_name}), 200

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
        conn.close()
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
            print("[Notice] Secret file 'brevo_key.txt' not found. Falling back to logs.")

    SENDER_EMAIL = "contact@driveelite.ph"

    if not BREVO_API_KEY:
        print(f"[OTP LOG FALLBACK] Email: {email} | Code: {code}")
        return jsonify({"status": "success", "message": "OTP Sent (Fallback)!"}), 200

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": BREVO_API_KEY,
                "Content-Type": "application/json"
            },
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
            print(f"Brevo API error: {response.text}")
            print(f"[OTP LOG FALLBACK] Email: {email} | Code: {code}")
            return jsonify({"status": "success", "message": "OTP Sent (Fallback)!"}), 200

    except Exception as e:
        print(f"API request failed: {str(e)}")
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
                query += " AND sq_teacher = ?"
                params.append(ans_teacher.strip().lower())
            if ans_dog is not None:
                query += " AND sq_dog = ?"
                params.append(ans_dog.strip().lower())
            if ans_food is not None:
                query += " AND sq_food = ?"
                params.append(ans_food.strip().lower())
            if ans_phone is not None:
                query += " AND sq_phone = ?"
                params.append(ans_phone.strip().lower())
            if ans_date is not None:
                query += " AND sq_date = ?"
                params.append(ans_date.strip().lower())

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
                query += " AND sq_teacher = ?"
                params.append(ans_teacher.strip().lower())
            if ans_dog is not None:
                query += " AND sq_dog = ?"
                params.append(ans_dog.strip().lower())
            if ans_food is not None:
                query += " AND sq_food = ?"
                params.append(ans_food.strip().lower())
            if ans_phone is not None:
                query += " AND sq_phone = ?"
                params.append(ans_phone.strip().lower())
            if ans_date is not None:
                query += " AND sq_date = ?"
                params.append(ans_date.strip().lower())

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


@app.route('/get_messages/<int:user1_id>/<int:user2_id>', methods=['GET'])
def get_messages(user1_id, user2_id):
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT from_user_id, to_user_id, content, timestamp 
        FROM messages 
        WHERE (from_user_id = ? AND to_user_id = ?) 
           OR (from_user_id = ? AND to_user_id = ?)
        ORDER BY id ASC
    ''', (user1_id, user2_id, user2_id, user1_id)).fetchall()
    conn.close()

    messages = []
    for r in rows:
        messages.append({
            "sender": r['from_user_id'],
            "text": r['content'],
            "timestamp": r['timestamp']
        })
    return jsonify({"status": "success", "messages": messages}), 200


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
        
        # 1. You like them
        conn.execute('''
            INSERT OR IGNORE INTO user_likes (from_user_id, to_user_id)
            VALUES (?, ?)
        ''', (from_user_id, to_user_id))
        
        # 2. SEAMLESS TESTING: They instantly like you back!
        conn.execute('''
            INSERT OR IGNORE INTO user_likes (from_user_id, to_user_id)
            VALUES (?, ?)
        ''', (to_user_id, from_user_id))
        
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


@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    if lat is not None and lng is not None:
        conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, current_user_id))
        conn.commit()

    # Pull user's preferences if they exist
    prefs = conn.execute('SELECT pref_age_min, pref_age_max, pref_genders, coffee_shop FROM users WHERE id = ?', (current_user_id,)).fetchone()
    
    age_min = prefs['pref_age_min'] if prefs and prefs['pref_age_min'] else 18
    age_max = prefs['pref_age_max'] if prefs and prefs['pref_age_max'] else 85
    user_shop = prefs['coffee_shop'] if prefs and prefs['coffee_shop'] else ""

    # Relaxed query: Added last_active to query
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

        # --- ONLINE STATUS CALCULATION ---
        last_active_str = u['last_active']
        is_online = False
        if last_active_str:
            try:
                last_act_dt = datetime.strptime(last_active_str, "%Y-%m-%d %H:%M:%S")
                if datetime.utcnow() - last_act_dt < timedelta(minutes=5):
                    is_online = True
            except Exception:
                pass

        # Fuzz coordinates for safety! (3 decimals is a ~100m radius)
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
    
    return jsonify({
        "status": "success",
        "feed": feed_list
    }), 200
        "user": {                 # <-- This will crash Python instantly!
            "id": user["id"],
            "nickname": user["nickname"],
            "age": user["age"],
            "coffee_shop": user["coffee_shop"],
            "bio": user["bio"],
            "image": img_url,
            "caffeine_status": user["caffeine_status"] if "caffeine_status" in user.keys() else "Chilling",
            "kyc_status": user["kyc_status"] if "kyc_status" in user.keys() else "Unverified",
            "is_premium": bool(user["is_premium"]) if "is_premium" in user.keys() else False,
            "is_online": is_online,
            "lat": round(user["last_lat"], 3) if user["last_lat"] is not None else None, # <-- ADD THIS
            "lng": round(user["last_lng"], 3) if user["last_lng"] is not None else None  # <-- ADD THIS
        }
    }), 200


@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    user_id = data.get('user_id')
    
    if user_id:
        # Save exact formatted string so it is easy to parse later
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

    # Profile online status logic
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
