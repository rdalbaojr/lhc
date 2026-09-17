import base64
import os
import random
import sqlite3
import time
import math
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


def get_db_connection():
    conn = sqlite3.connect('coffee_sparks.db')
    conn.row_factory = sqlite3.Row
    return conn

def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 999
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lon / 2)**2
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
            last_lng REAL
        )
    ''')
    
    migration_cols = [
        ('caffeine_status', "TEXT DEFAULT 'Craving an iced latte ☕'"), 
        ('audio_intro', 'TEXT'),
        ('last_lat', 'REAL'),
        ('last_lng', 'REAL')
    ]
    for col, col_type in migration_cols:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')
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
    try:
        cursor.execute('ALTER TABLE user_photos ADD COLUMN is_private INTEGER DEFAULT 1')
    except sqlite3.OperationalError:
        pass

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
    try:
        cursor.execute('ALTER TABLE date_invites ADD COLUMN message TEXT')
    except sqlite3.OperationalError:
        pass

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
    
    conn.commit()
    conn.close()


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "success", "message": "Coffee Sparks server is awake!"})

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
            INSERT INTO users (email, password, real_name, nickname, age, gender, coffee_shop, bio, profile_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (email, hashed_password, real_name, nickname, age, gender, coffee_shop, bio, avatar_filename))
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


@app.route('/upload_private_moment', methods=['POST'])
def upload_private_moment():
    user_id = request.form.get('user_id')
    caption = request.form.get('caption', '')
    file = request.files.get('image')
    
    if not user_id or not file:
        return jsonify({"status": "error", "message": "Missing user_id or image file"}), 400
        
    filename = secure_filename(f"moment_{user_id}_{int(time.time())}.jpg")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO private_moments (user_id, image_base64, caption) VALUES (?, ?, ?)',
                     (user_id, filename, caption)) # storing filename/path cleanly
        conn.commit()
        return jsonify({"status": "success", "message": "Saved!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()


@app.route('/get_secret_moments/<int:viewer_id>/<int:target_id>', methods=['GET'])
def get_secret_moments(viewer_id, target_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT id, image_base64, caption, timestamp FROM private_moments WHERE user_id = ? ORDER BY id DESC', (target_id,)).fetchall()
    conn.close()
    
    moments = []
    for r in rows:
        img_data = r['image_base64']
        # Strip out data URI scheme prefix if it accidentally got saved
        if img_data and ',' in img_data:
            img_data = img_data.split(',')[1]
            
        moments.append({
            "id": r['id'],
            "image": img_data,
            "caption": r['caption'] or "",
            "timestamp": r['timestamp']
        })
    return jsonify({"status": "success", "moments": moments}), 200


@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    conn = get_db_connection()
    if lat is not None and lng is not None:
        conn.execute('UPDATE users SET last_lat = ?, last_lng = ? WHERE id = ?', (lat, lng, current_user_id))
        conn.commit()
    
    cursor = conn.cursor()
    potential_matches = cursor.execute('''
        SELECT id, nickname, age, gender, coffee_shop, bio, profile_image, caffeine_status, last_lat, last_lng
        FROM users 
        WHERE id != ? AND last_lat IS NOT NULL AND last_lng IS NOT NULL
    ''', (current_user_id,)).fetchall()
    conn.close()

    feed_list = []
    MAX_DISTANCE_KM = 5.0

    for u in potential_matches:
        distance = haversine_distance(lat, lng, u['last_lat'], u['last_lng'])
        if distance <= MAX_DISTANCE_KM:
            avatar = u['profile_image']
            img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"
            
            feed_list.append({
                "id": u["id"],
                "name": u["nickname"] or "Anonymous",
                "age": str(u["age"] or 25),
                "shop": u["coffee_shop"] or "Local Cafe",
                "bio": u["bio"] or "Looking for good coffee and great conversation!",
                "image": img_url,
                "tags": ["Coffee Lover", u["caffeine_status"] or "Local", u["coffee_shop"] or "Explorer"],
                "distance_km": round(distance, 1)
            })
            
    feed_list.sort(key=lambda x: x['distance_km'])
    return jsonify({"status": "success", "feed": feed_list}), 200


@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/user_profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()

    if not user:
        return jsonify({
            "status": "success",
            "user": {
                "id": user_id,
                "nickname": "Coffee Lover",
                "age": 25,
                "coffee_shop": "Local Cafe",
                "bio": "Ready for coffee!",
                "image": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"
            }
        }), 200

    avatar = user['profile_image']
    img_url = f"{request.host_url}uploads/{avatar}" if avatar else "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"

    return jsonify({
        "status": "success",
        "user": {
            "id": user["id"],
            "nickname": user["nickname"],
            "age": user["age"],
            "coffee_shop": user["coffee_shop"],
            "bio": user["bio"],
            "image": img_url,
            "caffeine_status": user["caffeine_status"] if "caffeine_status" in user.keys() else "Chilling"
        }
    }), 200


@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    data = request.json or {}
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
        JOIN user_likes b ON a.from_user_id = b.to_user_id AND a.to_user_id = b.from_user_id
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
        rows = cursor.execute('SELECT u.id, u.nickname, u.age, u.coffee_shop, u.bio, u.profile_image FROM users u JOIN user_likes a ON u.id = a.to_user_id JOIN user_likes b ON u.id = b.from_user_id WHERE a.from_user_id = ? AND b.to_user_id = ?', (user_id, user_id)).fetchall()
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


if __name__ == '__main__':
    setup_database()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
