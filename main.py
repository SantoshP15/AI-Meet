from flask import Flask, request, render_template, send_file, jsonify
import whisper
import requests
import os
import re
import sqlite3
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
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
            timeout=200
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

    

def extract_timeline_from_transcript(transcript):
    number_words = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10"
}
    text = transcript.lower()

    # Convert word numbers → digits
    for word, digit in number_words.items():
        text = text.replace(word, digit)

    timeline_keywords = [
        "complete", "finish", "delivery", "timeline",
        "deadline", "duration", "take", "done in"
    ]

    patterns = [
        r'(\d+)\s*days?',
        r'(\d+)\s*weeks?',
        r'(\d+)\s*months?'
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            start = match.start()

            context = text[max(0, start-30):start]

            if any(keyword in context for keyword in timeline_keywords):
                return match.group(0)

    return None

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

def parse_mom_sections(text):
    sections = {
        "agenda": "",
        "discussion": "",
        "actions": ""
    }

    current = None

    for line in text.split("\n"):
        line_lower = line.lower()

        if "agenda" in line_lower:
            current = "agenda"
            continue
        elif "discussion" in line_lower:
            current = "discussion"
            continue
        elif "action" in line_lower:
            current = "actions"
            continue

        if current:
            sections[current] += line + " "

    return sections

def generate_mom_pdf(sections, attendees, timeline, file_path="summary.pdf"):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(file_path)

    elements = []

    # ===== HEADER =====
    elements.append(Paragraph("<font size=26 color='orange'><b>Minutes</b></font>", styles["Title"]))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(f"<b>Timeline:</b> {timeline}", styles["Normal"]))
    elements.append(Spacer(1, 15))
    elements.append(Paragraph("<b>Meeting Title:</b> AI Generated Meeting", styles["Normal"]))
    elements.append(Paragraph("<b>Date & Time:</b> Auto Generated", styles["Normal"]))
    elements.append(Paragraph("<b>Location:</b> Virtual", styles["Normal"]))
    elements.append(Spacer(1, 20))

    # ===== GRID CONTENT =====
    table_data = [
        [
           Paragraph("<b>Attendees</b><br/>" + "<br/>".join(attendees), styles["Normal"]),
            Paragraph("<b>Agenda</b><br/>" + sections["agenda"], styles["Normal"])
        ],
        [
            Paragraph("<b>Absentees</b><br/>-", styles["Normal"]),
            Paragraph("<b>Discussion</b><br/>" + sections["discussion"], styles["Normal"])
        ],
        [
            Paragraph("<b>Icebreaker</b><br/>-", styles["Normal"]),
            Paragraph("<b>Shoutouts</b><br/>-", styles["Normal"])
        ],
        [
            Paragraph("<b>Action Items</b><br/>" + sections["actions"], styles["Normal"]),
            Paragraph("<b>Parking Lot</b><br/>-", styles["Normal"])
        ],
    ]

    table = Table(table_data, colWidths=[270, 270])

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1, colors.orange),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    elements.append(table)

    doc.build(elements)

def detect_attendees_from_transcript(transcript):
    employees = df["Name"].dropna().tolist()
    transcript_lower = transcript.lower()

    attendees = []

    for emp in employees:
        emp_parts = emp.lower().split()  # ["santosh", "patil"]

        # Check if ANY part of name exists in transcript
        for part in emp_parts:
            if part in transcript_lower:
                attendees.append(emp)
                break  # avoid duplicate match

    return list(set(attendees))  # remove duplicates
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
Generate a structured Minutes of Meeting from the transcript.

Return in this format:

Agenda:
...

Discussion:
...

Action Items:
...

Transcript:
{transcript}
"""

        summary = call_llm(prompt)
        sections = parse_mom_sections(summary)
        attendees = detect_attendees_from_transcript(transcript)
        timeline = extract_timeline_from_transcript(transcript)
        if not timeline:
            timeline = "Not mentioned"
        print("Detected attendees:", attendees)
        # Save to DB
        conn = get_db()
        conn.execute(
            "INSERT INTO meetings (filename, transcript, summary) VALUES (?, ?, ?)",
            (filename, transcript, summary)
        )
        conn.commit()
        conn.close()

        return render_template(
    "result.html",
    transcript=transcript,
    summary=summary,
    attendees=attendees,
    sections=sections,
    timeline=timeline
)
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
    sections = parse_mom_sections(summary)
    attendees = request.args.get("attendees", "")
    attendees_list = attendees.split(",") if attendees else []
    timeline = request.args.get("timeline", "Not mentioned")

    generate_mom_pdf(sections, attendees_list, timeline, file_path)

    return send_file(file_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)