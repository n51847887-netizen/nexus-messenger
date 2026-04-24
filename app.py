from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from datetime import datetime
import os
import uuid

app = Flask(__name__)

# ─── CONFIG ─────────────────────────────
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─── SIMPLE ONLINE TRACKING ─────────────
online_users = {}

# ─── MODELS (минимум) ───────────────────
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat = db.Column(db.String(50))
    user = db.Column(db.String(50))
    text = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.utcnow)

# ─── HELPERS ────────────────────────────
def current_user():
    uid = session.get("user")
    return uid

# ─── AUTH ───────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()

    if not user:
        return jsonify({"error": "no user"}), 401

    if not bcrypt.check_password_hash(user.password, data["password"]):
        return jsonify({"error": "wrong pass"}), 401

    session["user"] = user.username
    return jsonify({"ok": True, "user": user.username})


@app.route("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})

# ─── SOCKET ─────────────────────────────
@socketio.on("connect")
def connect():
    user = current_user()
    if not user:
        return False

    online_users[request.sid] = user
    print("CONNECTED:", user)


@socketio.on("disconnect")
def disconnect():
    online_users.pop(request.sid, None)


@socketio.on("join")
def join(data):
    join_room(data["chat"])


@socketio.on("message")
def message(data):
    user = online_users.get(request.sid)
    if not user:
        return

    msg = Message(
        chat=data["chat"],
        user=user,
        text=data["text"]
    )

    db.session.add(msg)
    db.session.commit()

    emit("message", {
        "chat": msg.chat,
        "user": msg.user,
        "text": msg.text
    }, room=data["chat"])

# ─── ROUTE ──────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─── START ──────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
