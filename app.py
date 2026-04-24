from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime, timedelta
import os
import uuid
import random

app = Flask(__name__)

# ─── CONFIG ─────────────────────────────────────────────
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")
db_url = os.environ.get("DATABASE_URL", "sqlite:///nexus.db")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# ⚠️ ВАЖНО: threading (СТАБИЛЬНО НА RENDER)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

# ─── SIMPLE ONLINE TRACK ───────────────────────────────
online_users = {}

# ─── MODELS ─────────────────────────────────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    display_name = db.Column(db.String(100))
    password = db.Column(db.String(200))
    online = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    content = db.Column(db.Text)
    chat_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─── HELPERS ────────────────────────────────────────────
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)

# ─── ROUTES ─────────────────────────────────────────────
@app.route("/")
def index():
    return "SERVER OK"

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()

    if not user:
        return jsonify({"error": "no user"}), 401

    session["user_id"] = user.id
    user.online = True
    db.session.commit()

    return jsonify({"ok": True})

@app.route("/api/auth/logout", methods=["POST"])
def logout():
    user = current_user()
    if user:
        user.online = False
        db.session.commit()

    session.clear()
    return jsonify({"ok": True})

# ─── SOCKETS ───────────────────────────────────────────
@socketio.on("connect")
def connect():
    user = current_user()
    if not user:
        return False

    online_users[request.sid] = user.id
    user.online = True
    db.session.commit()

    emit("online", {"user_id": user.id}, broadcast=True)

@socketio.on("disconnect")
def disconnect():
    uid = online_users.pop(request.sid, None)

    if uid:
        user = db.session.get(User, uid)
        if user:
            user.online = False
            db.session.commit()

@socketio.on("send_message")
def send_message(data):
    user = current_user()
    if not user:
        return

    msg = Message(
        user_id=user.id,
        chat_id=data.get("chat_id", 1),
        content=data.get("content", "")
    )

    db.session.add(msg)
    db.session.commit()

    emit("new_message", {
        "user_id": user.id,
        "content": msg.content
    }, broadcast=True)

# ─── START ──────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        allow_unsafe_werkzeug=True
    )
