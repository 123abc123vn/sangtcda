import time
from pyngrok import ngrok

print("Starting ngrok tunnel for port 8000...")
public_url = ngrok.connect(8000)
print(f"\n==========================================")
print(f"NGROK PUBLIC URL: {public_url.public_url}")
print(f"==========================================\n")

# Keep the script running
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Closing tunnel...")
