from flask import Flask, request, render_template, send_file, jsonify
import whisper
import requests
import os
import sqlite3
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
from werkzeug.utils import secure_filename

# =========================
# CONFIG
# =========================
app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"mp3", "wav", "m4a"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load model once (better performance)
model = whisper.load_model("base")

# Load employee data once
df = pd.read_excel("employees.xlsx")

# =========================
# DB CONNECTION (BETTER)
# =========================
def get_db():
    conn = sqlite3.connect("meetings.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS meetings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT,
        transcript TEXT,
        summary TEXT
    )
    """)
    conn.commit()
    conn.close()

init_db()

# =========================
# UTIL FUNCTIONS
# =========================
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def call_llm(prompt):
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3", "prompt": prompt, "stream": False},
            timeout=60
        )
        return response.json().get("response", "No response from LLM")
    except Exception as e:
        return f"LLM Error: {str(e)}"


# =========================
# AI LOGIC
# =========================
def detect_roles(requirement):
    req = requirement.lower()
    roles = ["Project Manager"]

    mapping = {
        "dashboard": "Power BI Developer",
        "power bi": "Power BI Developer",
        "backend": "Backend Developer",
        "database": "Backend Developer"
    }

    for key, role in mapping.items():
        if key in req:
            roles.append(role)

    return list(set(roles))


def select_team(df, roles):
    team = []

    for role in roles:
        candidates = df[(df["Role"] == role) & (df["Available"] == "Yes")]

        if not candidates.empty:
            best = (
                candidates.sort_values(by="Experience", ascending=False).iloc[0]
                if "Experience" in df.columns
                else candidates.iloc[0]
            )
            team.append(best)

    return pd.DataFrame(team)


def calculate_cost(team, months=1, profit_margin=0.3):
    total_salary = team["Salary"].sum()
    base_cost = total_salary * months
    final_cost = int(base_cost * (1 + profit_margin))
    return base_cost, final_cost


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process", methods=["POST"])
def process_audio():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(file_path)

    language = request.form.get("language", "hi")

    try:
        # Transcription
        result = model.transcribe(file_path, language=language)
        transcript = result["text"]

        # Summary
        prompt = f"""
        Generate a Minutes of meeting of the given Transcript

        Transcript:
        {transcript}
        """

        summary = call_llm(prompt)

        # Save to DB
        conn = get_db()
        conn.execute(
            "INSERT INTO meetings (filename, transcript, summary) VALUES (?, ?, ?)",
            (filename, transcript, summary)
        )
        conn.commit()
        conn.close()

        return render_template("result.html", transcript=transcript, summary=summary)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/quotation", methods=["POST"])
def quotation():
    requirement = request.form.get("requirement", "")

    roles = detect_roles(requirement)
    team = select_team(df, roles)
    base_cost, final_cost = calculate_cost(team)

    team_info = "\n".join(
        [f"{row['Name']} - {row['Role']} (₹{row['Salary']})" for _, row in team.iterrows()]
    )

    prompt = f"""
    Create a professional quotation and timeline for work

    Client Requirement:
    {requirement}

    Team:
    {team_info}

    Base Cost: ₹{base_cost}
    Final Cost: ₹{final_cost}
    """

    quotation = call_llm(prompt)

    return render_template("quotation_result.html", quotation=quotation)


@app.route("/download")
def download_pdf():
    summary = request.args.get("summary", "")

    file_path = "summary.pdf"
    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = [Paragraph(summary, styles["Normal"])]
    doc.build(content)

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)