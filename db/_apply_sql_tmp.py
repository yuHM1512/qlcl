import os
from dotenv import load_dotenv
import psycopg2
from pathlib import Path

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

sql_path = Path(r"D:\Data Analyst\Tools\kpi\qlcl\db\create_qc_output_sp_log.sql")
sql = sql_path.read_text(encoding="utf-8")

with psycopg2.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()

print("Applied: create_qc_output_sp_log.sql")
