import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

def get_cols(table):
    cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{table}';")
    print(f"--- {table} ---")
    for row in cur.fetchall():
        print(row)

get_cols('qc_error_log')
get_cols('qc_defect')
