import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("=== TESTING FASTAPI ROOT & HEALTH ===")
r_root = client.get("/")
print("Root status:", r_root.status_code, r_root.json())
assert r_root.status_code == 200

r_health = client.get("/health")
print("Health status:", r_health.status_code, r_health.json())
assert r_health.status_code == 200

print("✅ FastAPI service successfully initialized and responding!")
