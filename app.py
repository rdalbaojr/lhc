import base64
import os
import random
import time
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import requests

app = Flask(__name__)
CORS(app)

# -----------------------------------------------------------
# YOUR NEON POSTGRESQL CONNECTION
# -----------------------------------------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = "postgresql+psycopg2://neondb_owner:npg_daE6fcPxb8Wt@ep-dawn-bird-b3t81mqc-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ==========================================
# DATABASE MODELS
# ==========================================
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    real_name = db.Column(db.String(100), nullable=False)
    nickname = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(50))
    coffee_shop = db.Column(db.String(100))
    bio = db.Column(db.Text)
    profile_image = db.Column(db.String(255))
    caffeine_status = db.Column(db.String(100), default='Craving an iced latte ☕')
    audio_intro = db.Column(db.Text)

class UserPhoto(db.Model):
    __tablename__ = 'user_photos'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    caption = db.Column(db.Text)
    is_private = db.Column(db.Integer, default=1)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserLike(db.Model):
    __tablename__ = 'user_likes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('from_user_id', 'to_user_id', name='unique_like'),)

class DateInvite(db.Model):
    __tablename__ = 'date_invites'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    cafe_name = db.Column(db.String(255), nullable=False)
    meet_time = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
# Force Render to build the tables when it wakes up!
with app.app_context():
    db.create_all()

# ==========================================
# GOOGLE MAPS GPS TRANSLATION
# ==========================================
def get_nearest_cafe(lat, lng):
    if not lat or not lng:
        return None

    # TODO: Paste your actual Google Cloud API Key here!
    GOOGLE_API_KEY = "AIzaSyBARV7naQiJJdcq-3YDV36s5cFutfLq9dg"
    
    try:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            'location': f"{lat},{lng}",
            'radius': 1000,
            'type': 'cafe',
            'keyword': 'coffee',
            'key': GOOGLE_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if data.get('status') == 'OK' and data.get('results'):
            return data['results'][0].get('name')
            
    except Exception as e:
        print(f"🚨 Google Maps API error: {e}")
        
    return f"Lat {round(lat, 3)}, Lng {round(lng, 3)}"

# ==========================================
# API ENDPOINTS
# ==========================================
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "success", "message": "Coffee Sparks server is awake!"})

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email', f"user_{int(time.time())}@coffee.com")
    
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

    new_user = User(
        email=email,
        password=data.get('password', 'temporarypassword'),
        real_name=data.get('real_name', 'Coffee Lover'),
        nickname=data.get('nickname', data.get('real_name', 'Coffee Lover')),
        age=int(data.get('age', 18)),
        gender=data.get('gender', 'Man'),
        coffee_shop=data.get('coffee_shop', 'Local Cafe'),
        bio=data.get('bio', ''),
        profile_image=avatar_filename
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"status": "success", "message": "Profile registered!", "user_id": new_user.id}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Email already exists."}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    lat = data.get('lat')
    lng = data.get('lng')

    print(f"🚨 DEBUG LOGIN - Email: {email} | Lat: {lat} | Lng: {lng}")

    user = User.query.filter_by(email=email, password=password).first()
    
    if not user: 
        return jsonify({"error": "Invalid"}), 401
    
    if lat and lng:
        nearest_cafe = get_nearest_cafe(lat, lng)
        if nearest_cafe:
            user.coffee_shop = nearest_cafe
            db.session.commit()
            print(f"Updated user's location to: {nearest_cafe}")

    return jsonify({"message": "Login successful", "user_id": user.id}), 200

@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json or {}
    user = User.query.get(data.get('user_id', 1))
    if user:
        user.caffeine_status = data.get('caffeine_status', 'Chilling at a cafe')
        db.session.commit()
    return jsonify({"status": "success", "caffeine_status": user.caffeine_status if user else ""}), 200

@app.route('/create_date_invite', methods=['POST'])
def create_date_invite():
    data = request.json or {}
    invite = DateInvite(
        from_user_id=data.get('from_user_id'),
        to_user_id=data.get('to_user_id'),
        cafe_name=data.get('cafe_name', 'Local Cafe'),
        meet_time=data.get('meet_time', 'Tomorrow at 3 PM')
    )
    db.session.add(invite)
    db.session.commit()
    return jsonify({"status": "success", "message": "Date invite sent!"}), 201

@app.route('/daily_prompt', methods=['GET'])
def get_daily_prompt():
    prompts = [
        "Dark roast purist or sweet caramel macchiato fan?",
        "What is your ultimate go-to pastry pairing with an iced latte?",
        "Morning espresso shot for energy or slow evening pour-over?",
        "Have you ever accidentally stayed at a coffee shop for over 4 hours?"
    ]
    return jsonify({"status": "success", "prompt": random.choice(prompts)}), 200

@app.route('/feed', methods=['GET'])
def get_feed():
    current_user_id = request.args.get('user_id', default=1, type=int)
    current_user = User.query.get(current_user_id)
    current_shop = current_user.coffee_shop.lower() if current_user and current_user.coffee_shop else ""

    users = User.query.filter(User.id != current_user_id).all()
    users.sort(key=lambda u: (u.coffee_shop.lower() == current_shop if u.coffee_shop else False), reverse=True)

    feed_list = []
    for u in users:
        img_url = f"{request.host_url}uploads/{u.profile_image}" if u.profile_image else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=800&q=80"
        feed_list.append({
            "id": u.id,
            "name": u.nickname or "Anonymous",
            "age": str(u.age or 25),
            "shop": u.coffee_shop or "Local Cafe",
            "bio": u.bio or "Looking for good coffee and great conversation!",
            "image": img_url,
            "tags": ["Coffee Lover", u.caffeine_status or "Local", u.coffee_shop or "Explorer"]
        })
    return jsonify({"status": "success", "feed": feed_list}), 200

@app.route('/uploads/<path:filename>')
def serve_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/user_profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"status": "error", "message": "User not found"}), 404

    img_url = f"{request.host_url}uploads/{user.profile_image}" if user.profile_image else "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=800&q=80"
    return jsonify({
        "status": "success",
        "user": {
            "id": user.id,
            "real_name": user.real_name,
            "nickname": user.nickname,
            "age": user.age,
            "coffee_shop": user.coffee_shop,
            "bio": user.bio,
            "image": img_url,
            "caffeine_status": user.caffeine_status
        }
    }), 200

@app.route('/update_avatar', methods=['POST'])
def update_avatar():
    user_id = request.form.get('user_id', 1, type=int)
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files['file']
    filename = secure_filename(f"avatar_{user_id}_{int(time.time())}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    user = User.query.get(user_id)
    if user:
        user.profile_image = filename
        db.session.commit()

    return jsonify({"status": "success", "avatar_url": f"{request.host_url}uploads/{filename}"}), 200

@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    user_id = request.form.get('user_id', 1, type=int)
    if 'file' not in request.files or request.files['file'].filename == '':
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files['file']
    filename = secure_filename(f"user_{user_id}_{int(time.time())}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    is_private_val = 1 if request.form.get('is_private', '1') in ['1', 'true', 'True'] else 0
    new_photo = UserPhoto(
        user_id=user_id,
        image_filename=filename,
        caption=request.form.get('caption', ''),
        is_private=is_private_val
    )
    db.session.add(new_photo)
    db.session.commit()

    return jsonify({"status": "success", "image_url": f"{request.host_url}uploads/{filename}"}), 201

@app.route('/toggle_photo_privacy', methods=['POST'])
def toggle_photo_privacy():
    data = request.json or {}
    photo = UserPhoto.query.filter_by(id=data.get('photo_id'), user_id=data.get('user_id', 1)).first()
    
    if not photo:
        return jsonify({"status": "error", "message": "Photo not found"}), 404

    photo.is_private = 0 if photo.is_private == 1 else 1
    db.session.commit()
    return jsonify({"status": "success", "is_private": bool(photo.is_private)}), 200

@app.route('/user_photos/<int:user_id>', methods=['GET'])
def get_user_photos(user_id):
    photos = UserPhoto.query.filter_by(user_id=user_id).order_by(UserPhoto.id.desc()).all()
    result = [{
        "id": p.id,
        "image_url": f"{request.host_url}uploads/{p.image_filename}",
        "caption": p.caption or "",
        "is_private": bool(p.is_private)
    } for p in photos]
    
    return jsonify({"status": "success", "photos": result}), 200

@app.route('/like_user', methods=['POST'])
def like_user():
    data = request.json or {}
    from_user, to_user = data.get('from_user_id'), data.get('to_user_id')

    if not from_user or not to_user:
        return jsonify({"status": "error", "message": "Missing user IDs"}), 400

    existing_like = UserLike.query.filter_by(from_user_id=from_user, to_user_id=to_user).first()
    if not existing_like:
        db.session.add(UserLike(from_user_id=from_user, to_user_id=to_user))
        db.session.commit()

    mutual = UserLike.query.filter_by(from_user_id=to_user, to_user_id=from_user).first()
    return jsonify({"status": "success", "is_match": mutual is not None}), 200

@app.route('/user_stats/<int:user_id>', methods=['GET'])
def get_user_stats(user_id):
    user = User.query.get(user_id)
    current_shop = user.coffee_shop.lower() if user and user.coffee_shop else ""

    vibes_count = User.query.filter(
        db.func.lower(User.coffee_shop) == current_shop, 
        User.id != user_id
    ).count()

    likes_count = UserLike.query.filter_by(to_user_id=user_id).count()

    likes_sent = db.session.query(UserLike.to_user_id).filter_by(from_user_id=user_id).subquery()
    match_count = UserLike.query.filter(
        UserLike.to_user_id == user_id,
        UserLike.from_user_id.in_(likes_sent)
    ).count()

    return jsonify({"status": "success", "match_brew": match_count, "similar_vibes": vibes_count, "local_likes": likes_count}), 200

@app.route('/insight_details/<category>/<int:user_id>', methods=['GET'])
def get_insight_details(category, user_id):
    user = User.query.get(user_id)
    current_shop = user.coffee_shop.lower() if user and user.coffee_shop else ""
    users_list = []

    if category == 'similar_vibes':
        rows = User.query.filter(db.func.lower(User.coffee_shop) == current_shop, User.id != user_id).all()
        title = f"Similar Coffee Vibes ({user.coffee_shop})"
    elif category == 'local_likes':
        likers = db.session.query(UserLike.from_user_id).filter_by(to_user_id=user_id).subquery()
        rows = User.query.filter(User.id.in_(likers)).all()
        title = "Local Coffee Likes"
    elif category == 'match_brew':
        likes_sent = db.session.query(UserLike.to_user_id).filter_by(from_user_id=user_id).subquery()
        mutual_likers = db.session.query(UserLike.from_user_id).filter(
            UserLike.to_user_id == user_id, 
            UserLike.from_user_id.in_(likes_sent)
        ).subquery()
        rows = User.query.filter(User.id.in_(mutual_likers)).all()
        title = "Match Brew (Mutual Sparks)"
    else:
        return jsonify({"status": "error", "message": "Unknown category"}), 400

    for r in rows:
        img_url = f"{request.host_url}uploads/{r.profile_image}" if r.profile_image else "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=80"
        users_list.append({
            "id": r.id,
            "name": r.nickname or "Coffee Lover",
            "age": str(r.age or ""),
            "shop": r.coffee_shop or "Local Spot",
            "bio": r.bio or "Looking for great coffee & conversation!",
            "image": img_url
        })

    return jsonify({"status": "success", "title": title, "users": users_list}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
