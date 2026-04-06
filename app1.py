from flask import Flask, request, render_template, send_file
import whisper
import requests
import os
import sqlite3
import pandas as pd  
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)

model = whisper.load_model("base")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ✅ Load Employee Data
df = pd.read_excel("employees.xlsx")

# DB setup
conn = sqlite3.connect("meetings.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    transcript TEXT,
    summary TEXT
)
""")
conn.commit()


# =========================
# 🔥 AI LOGIC (NEW)
# =========================

def detect_roles(requirement):
    roles = ["Project Manager"]
    req = requirement.lower()

    if "dashboard" in req or "power bi" in req:
        roles.append("Power BI Developer")

    if "backend" in req or "database" in req:
        roles.append("Backend Developer")

    return roles


def select_team(df, roles):
    team = []

    for role in roles:
        candidates = df[(df["Role"] == role) & (df["Available"] == "Yes")]

        if not candidates.empty:
            # ✅ If Experience exists → use it
            if "Experience" in df.columns:
                best = candidates.sort_values(by="Experience", ascending=False).iloc[0]
            else:
               
                best = candidates.iloc[0]

            team.append(best)
    return team


def calculate_cost(team, months=1, profit_margin=0.3):
    total_salary = sum(member["Salary"] for member in team)
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
    file = request.files["file"]
    language = request.form.get("language", "hi")

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # Step 1: Transcription
    result = model.transcribe(file_path, language=language)
    transcript = result["text"]

    # Step 2: Summary
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": f"""
            Convert into bullet points:

            1. Key Points
            2. Action Items
            3. Decisions

            Transcript:
            {transcript}
            """,
            "stream": False
        }
    )

    summary = response.json()["response"]

    # Save to DB
    cursor.execute(
        "INSERT INTO meetings (filename, transcript, summary) VALUES (?, ?, ?)",
        (file.filename, transcript, summary)
    )
    conn.commit()

    # ✅ PASS TRANSCRIPT FOR QUOTATION
    return render_template(
        "result.html",
        transcript=transcript,
        summary=summary
    )


# =========================
# 🔥 NEW: QUOTATION ROUTE
# =========================

@app.route("/quotation", methods=["POST"])
def quotation():
    requirement = request.form["requirement"]

    # Step 1: Detect roles
    roles = detect_roles(requirement)

    # Step 2: Select team
    team = select_team(df, roles)

    # Step 3: Cost calculation
    base_cost, final_cost = calculate_cost(team)

    # Convert team info
    team_info = "\n".join([
        f"{member['Name']} - {member['Role']} (₹{member['Salary']})"
        for _, member in pd.DataFrame(team).iterrows()
    ])

    prompt = f"""
    Create a professional quotation.

    Client Requirement:
    {requirement}

    Selected Team:
    {team_info}

    Base Cost: ₹{base_cost}
    Final Cost: ₹{final_cost}

    Include:
    - Project Overview
    - Team Structure with responsiblities
    - Cost Breakdown in detail
    - Justification
    """

    response = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }
    )

    quotation = response.json()["response"]

    return render_template("quotation_result.html", quotation=quotation)


# =========================
# PDF DOWNLOAD
# =========================

@app.route("/download")
def download_pdf():
    summary = request.args.get("summary")

    file_path = "summary.pdf"

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = [Paragraph(summary, styles["Normal"])]

    doc.build(content)

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)