import json
import os
from datetime import datetime
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import (
    UserMixin,
    login_required,
    login_user,
    logout_user,
    current_user,
    LoginManager,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["SECRET_KEY"] = "school-portal-secret-key-2026"

# --- ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ (POSTGRESQL / SQLITE) ---
database_url = os.environ.get("DATABASE_URL")

# Исправление префикса для SQLAlchemy, если Render передает postgres://
if database_url and database_url.startswith("postgres://"):
  database_url = database_url.replace("postgres://", "postgresql://", 1)

# В облаке Render используем Neon PostgreSQL, локально — SQLite
app.config["SQLALCHEMY_DATABASE_URI"] = (
    database_url or "sqlite:///school_class.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Настройка папки для загрузки файлов (расписание, ДЗ)
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


# --- МОДЕЛИ БАЗЫ ДАННЫХ ---
class User(UserMixin, db.Model):
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  password_hash = db.Column(db.String(200), nullable=False)
  role = db.Column(db.String(20), nullable=False, default="student")  # admin, teacher, student, parent
  full_name = db.Column(db.String(120), nullable=False)
  parent_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

  def set_password(self, password):
    self.password_hash = generate_password_hash(password)

  def check_password(self, password):
    return check_password_hash(self.password_hash, password)


class Grade(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
  subject = db.Column(db.String(80), nullable=False)
  grade_value = db.Column(db.String(10), nullable=False)
  quarter = db.Column(db.Integer, nullable=False, default=1)
  date_added = db.Column(db.DateTime, default=datetime.utcnow)


class Announcement(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  content = db.Column(db.Text, nullable=False)
  date_posted = db.Column(db.DateTime, default=datetime.utcnow)


class Homework(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  subject = db.Column(db.String(80), nullable=False)
  task = db.Column(db.Text, nullable=False)
  file_path = db.Column(db.String(200), nullable=True)
  date_due = db.Column(db.String(20), nullable=False)


@login_manager.user_loader
def load_user(user_id):
  return User.query.get(int(user_id))


# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ И АДМИНИСТРАТОРА ---
with app.app_context():
  db.create_all()
  # Автоматическое создание аккаунта администратора по умолчанию
  if not User.query.filter_by(username="admin").first():
    admin = User(
        username="admin", full_name="Главный Администратор", role="admin"
    )
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()


# --- МАРШРУТЫ ПРИЛОЖЕНИЯ ---


@app.route("/")
def index():
  if current_user.is_authenticated:
    return redirect(url_for("dashboard"))
  return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
  if request.method == "POST":
    username = request.form.get("username")
    password = request.form.get("password")
    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
      login_user(user)
      return redirect(url_for("dashboard"))
    else:
      flash("Неверное имя пользователя или пароль", "danger")

  return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
  logout_user()
  return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
  announcements = (
      Announcement.query.order_by(Announcement.date_posted.desc()).limit(5).all()
  )
  homeworks = Homework.query.all()

  if current_user.role == "student":
    grades = Grade.query.filter_by(student_id=current_user.id).all()
  elif current_user.role == "parent":
    children = User.query.filter_by(parent_id=current_user.id).all()
    child_ids = [c.id for c in children]
    grades = Grade.query.filter(Grade.student_id.in_(child_ids)).all()
  else:
    grades = Grade.query.all()

  return render_template(
      "dashboard.html",
      announcements=announcements,
      homeworks=homeworks,
      grades=grades,
  )


@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
  if current_user.role not in ["admin", "teacher"]:
    flash("У вас нет доступа к этой странице", "danger")
    return redirect(url_for("dashboard"))

  students = User.query.filter_by(role="student").all()

  if request.method == "POST":
    action = request.form.get("action")

    # Добавление оценки
    if action == "add_grade":
      student_id = request.form.get("student_id")
      subject = request.form.get("subject")
      grade_value = request.form.get("grade_value")
      quarter = request.form.get("quarter", 1)

      new_grade = Grade(
          student_id=student_id,
          subject=subject,
          grade_value=grade_value,
          quarter=quarter,
      )
      db.session.add(new_grade)
      db.session.commit()
      flash("Оценка успешно добавлена!", "success")

    # Добавление объявления
    elif action == "add_announcement":
      title = request.form.get("title")
      content = request.form.get("content")
      new_ann = Announcement(title=title, content=content)
      db.session.add(new_ann)
      db.session.commit()
      flash("Объявление опубликовано!", "success")

    # Добавление ДЗ
    elif action == "add_homework":
      subject = request.form.get("subject")
      task = request.form.get("task")
      date_due = request.form.get("date_due")

      file = request.files.get("file")
      filename = None
      if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

      new_hw = Homework(
          subject=subject, task=task, file_path=filename, date_due=date_due
      )
      db.session.add(new_hw)
      db.session.commit()
      flash("Домашнее задание добавлено!", "success")

    return redirect(url_for("admin"))

  return render_template("admin.html", students=students)


@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
  return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
  app.run(debug=True)