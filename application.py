import os

import boto3
import psycopg2
from flask import Flask

application = Flask(__name__)

VERSION_FILE = os.path.join(os.path.dirname(__file__), "version.txt")
try:
    with open(VERSION_FILE) as f:
        VERSION = f.read().strip()
except FileNotFoundError:
    VERSION = "dev"

_db_password = None


def get_db_password():
    # Resolved here at runtime via the instance's own IAM role, not passed as a plain EB env var.
    global _db_password
    if _db_password is None:
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        response = ssm.get_parameter(Name=os.environ["DB_PASSWORD_PARAM"], WithDecryption=True)
        _db_password = response["Parameter"]["Value"]
    return _db_password


def get_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=get_db_password(),
    )


def record_visit():
    conn = get_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS visits (
                    id SERIAL PRIMARY KEY,
                    visited_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            cur.execute("INSERT INTO visits DEFAULT VALUES")
            cur.execute("SELECT COUNT(*) FROM visits")
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        conn.close()


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Beanstalk Lab App</title>
  <style>
    body {{
      font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }}
    .card {{
      background: #1e293b;
      border-radius: 12px;
      padding: 2.5rem 3rem;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
      text-align: center;
    }}
    h1 {{
      color: #4ade80;
      margin: 0 0 0.5rem;
    }}
    p {{
      color: #94a3b8;
      margin: 0;
    }}
    .row {{
      display: flex;
      gap: 1.5rem;
      margin-top: 1.5rem;
      justify-content: center;
    }}
    .stat {{
      background: #0f172a;
      border-radius: 8px;
      padding: 1rem 1.5rem;
      min-width: 120px;
    }}
    .stat .label {{
      font-size: 0.75rem;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .stat .value {{
      font-size: 1.5rem;
      font-weight: 700;
      margin-top: 0.25rem;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Deployment Successful</h1>
    <p>This Python app is running on AWS Elastic Beanstalk v2</p>
    <div class="row">
      <div class="stat">
        <div class="label">Version</div>
        <div class="value">{version}</div>
      </div>
      <div class="stat">
        <div class="label">Visits</div>
        <div class="value">{visits}</div>
      </div>
    </div>
  </div>
</body>
</html>
"""


@application.route("/")
def index():
    return PAGE_TEMPLATE.format(version=VERSION, visits=record_visit())


@application.route("/visits")
def visits_json():
    return {"status": "ok", "visits": record_visit()}


if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8000)
