from flask import Flask, render_template, request, redirect
from datetime import datetime
import os
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ------------------- Upload Config -------------------
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ------------------- Database -------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ------------------- Models -------------------

class Complaint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    issue = db.Column(db.Text)
    location = db.Column(db.String(200))
    landmark = db.Column(db.String(200))
    category = db.Column(db.String(50))
    priority = db.Column(db.String(10))
    score = db.Column(db.Integer)
    count = db.Column(db.Integer, default=1)
    photo = db.Column(db.String(300))
    time = db.Column(db.String(50))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    points = db.Column(db.Integer, default=0)
    level = db.Column(db.String(20), default="Bronze")

class Challenge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    description = db.Column(db.Text)
    points_reward = db.Column(db.Integer)
    completed_by = db.Column(db.Text, default="")

# ------------------- INIT DB -------------------
with app.app_context():
    db.create_all()

# ------------------- AI CLASSIFICATION -------------------
def classify_issue(text):
    text = text.lower()

    mapping = {
        "Waste Management": ["garbage", "trash", "waste"],
        "Road Damage": ["pothole", "road"],
        "Water Issue": ["leak", "water", "drain"],
        "Electricity Issue": ["power", "light", "wire"],
        "Traffic Issue": ["traffic", "jam"],
        "Noise Pollution": ["noise"],
        "Air Pollution": ["smoke"],
        "Flooding": ["flood"],
        "Open Manhole": ["manhole"]
    }

    category = "General"
    for cat, keywords in mapping.items():
        if any(word in text for word in keywords):
            category = cat
            break

    # AI Priority
    if any(w in text for w in ["fire", "gas leak", "shock", "accident"]):
        priority = "High"
    elif any(w in text for w in ["leak", "pothole", "garbage"]):
        priority = "Medium"
    else:
        priority = "Low"

    return category, priority

# ------------------- PRIORITY ENGINE -------------------
def get_priority_score(priority):
    return {"High": 10, "Medium": 6, "Low": 3}.get(priority, 5)

def update_dynamic_priority(c):
    if c.count >= 5:
        c.priority = "High"
    elif c.count >= 3:
        c.priority = "Medium"

    try:
        created = datetime.strptime(c.time, "%d %b %Y, %H:%M")
        hours = (datetime.now() - created).total_seconds() / 3600

        if hours > 48:
            c.priority = "High"
        elif hours > 24 and c.priority == "Low":
            c.priority = "Medium"
    except:
        pass

# ------------------- LEVEL SYSTEM -------------------
def get_level(points):
    if points >= 100:
        return "Gold"
    elif points >= 50:
        return "Silver"
    return "Bronze"

# ------------------- ROUTES -------------------

@app.route('/')
def home():
    return render_template('index.html')

# ------------------- SUBMIT COMPLAINT -------------------
@app.route('/submit', methods=['POST'])
def submit():
    name = request.form['name']
    issue = request.form['issue']
    location = request.form['location']
    landmark = request.form['landmark']

    file = request.files.get('photo')
    filepath = ""

    if file and file.filename:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

    category, priority = classify_issue(issue)
    score = get_priority_score(priority)

    user = User.query.filter_by(name=name).first()
    if not user:
        user = User(name=name)
        db.session.add(user)

    # Check duplicate complaint
    existing = Complaint.query.filter(
        Complaint.location.ilike(f"%{location}%"),
        Complaint.issue.ilike(f"%{issue}%")
    ).first()

    if existing:
        existing.count += 1
        update_dynamic_priority(existing)
        existing.score = get_priority_score(existing.priority)
        user.points += 2
    else:
        complaint = Complaint(
            name=name,
            issue=issue,
            location=location,
            landmark=landmark,
            category=category,
            priority=priority,
            score=score,
            count=1,
            photo=filepath,
            time=datetime.now().strftime("%d %b %Y, %H:%M")
        )
        db.session.add(complaint)
        user.points += score * 2

    user.level = get_level(user.points)

    db.session.commit()

    return redirect(f'/challenges?user={name}')

# ------------------- ADMIN DASHBOARD -------------------
@app.route('/admin')
def admin():
    complaints = Complaint.query.all()

    for c in complaints:
        update_dynamic_priority(c)
        c.score = get_priority_score(c.priority)

    db.session.commit()

    complaints = sorted(complaints, key=lambda x: (-x.score, -x.count))

    return render_template('admin.html', complaints=complaints)

# ------------------- STATS -------------------
@app.route('/stats')
def stats():
    complaints = Complaint.query.all()

    data = {
        "high": sum(1 for c in complaints if c.priority == "High"),
        "medium": sum(1 for c in complaints if c.priority == "Medium"),
        "low": sum(1 for c in complaints if c.priority == "Low"),
        "total": len(complaints)
    }

    users = User.query.all()
    leaderboard = sorted(users, key=lambda x: x.points, reverse=True)

    return render_template('stats.html', data=data, leaderboard=leaderboard)

# ------------------- CHALLENGES -------------------
@app.route('/challenges')
def show_challenges():
    user_name = request.args.get('user', 'Guest')

    user = User.query.filter_by(name=user_name).first()
    if not user:
        user = User(name=user_name)
        db.session.add(user)
        db.session.commit()

    challenges = Challenge.query.all()

    for c in challenges:
        c.completed_list = c.completed_by.split(',') if c.completed_by else []

    return render_template('challenges.html', challenges=challenges, user=user)

# ------------------- COMPLETE CHALLENGE -------------------
@app.route('/complete_challenge', methods=['POST'])
def complete_challenge():
    cid = int(request.form['challenge_id'])
    user_name = request.form['user_name']

    challenge = Challenge.query.get(cid)
    user = User.query.filter_by(name=user_name).first()

    completed = challenge.completed_by.split(',') if challenge.completed_by else []

    if user_name not in completed:
        completed.append(user_name)
        challenge.completed_by = ",".join(completed)

        # ✅ FIXED: Proper points update
        user.points = user.points + challenge.points_reward
        user.level = get_level(user.points)

    db.session.commit()

    return redirect(f'/challenges?user={user_name}')

# ------------------- SEED DATA -------------------
with app.app_context():
    if Challenge.query.count() == 0:
        db.session.add_all([
            Challenge(title="Plant a Tree", description="Plant at least 1 tree", points_reward=10),
            Challenge(title="Recycle Waste", description="Segregate waste for 1 week", points_reward=15),
            Challenge(title="Report Water Leaks", description="Report 3 leaks", points_reward=20)
        ])
        db.session.commit()

# ------------------- RUN -------------------
if __name__ == '__main__':
    app.run(debug=True)