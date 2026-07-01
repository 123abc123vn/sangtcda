import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = "https://iktnkckeegaejbubtscw.supabase.co"
SUPABASE_KEY = "sb_publishable_GqYbZ0kFcwRkiGK9oJKVjA_MFJjH7hE"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    response = supabase.table('knowledge').select('*').limit(1).execute()
    print("SUCCESS: Kết nối Supabase thành công!")
    print(response.data)
except Exception as e:
    print(f"ERROR: {e}")
