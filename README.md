# 🤖 AI Bridge — ERP BCS

Microservice Python (FastAPI) yang menjadi jembatan antara Frontend SvelteKit, Openclaw LLM, dan PostgreSQL Database.

## Arsitektur

```
Browser → SvelteKit → [AI Bridge] → Openclaw (LLM)
                          ↕
                      PostgreSQL (Data)
```

## Struktur Project

```
ai-bridge/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py             # Environment configuration
│   ├── database.py           # Async PostgreSQL connection
│   ├── routers/
│   │   └── chat.py           # POST /chat — endpoint utama
│   ├── agents/
│   │   ├── intent_detector.py    # Deteksi intent dari pesan user
│   │   └── hris_agent.py         # Koordinator AI untuk HRIS
│   ├── tools/
│   │   └── employees.py      # Query data karyawan
│   └── llm/
│       └── openclaw_client.py    # Openclaw API wrapper
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Cara Menjalankan

### Lokal (Development)

```bash
# 1. Masuk ke folder ai-bridge
cd ai-bridge

# 2. Buat virtual environment
python -m venv venv
source venv/bin/activate   # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy & edit environment
cp .env.example .env
# Edit .env sesuai konfigurasi server

# 5. Jalankan
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
# Dari root project (erp-bcs/)
docker compose up ai-bridge -d
```

## API Endpoints

| Method | Path      | Deskripsi                          |
|--------|-----------|------------------------------------|
| POST   | `/chat`   | Kirim pesan, dapat streaming AI    |
| GET    | `/health` | Health check (DB + service status) |
| GET    | `/docs`   | Swagger UI (auto-generated)        |
| GET    | `/`       | Service info                       |

## Contoh Request

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Berapa jumlah karyawan aktif?"}]}'
```

## Environment Variables

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `OPENCLAW_BASE_URL` | `http://127.0.0.1:8080/v1` | URL server Openclaw |
| `OPENCLAW_API_KEY` | `openclaw-key` | API Key Openclaw |
| `OPENCLAW_MODEL` | `glm-4.7-flash` | Model AI yang digunakan |
| `DATABASE_URL` | (lihat .env.example) | PostgreSQL connection string |
| `AI_BRIDGE_PORT` | `8000` | Port service |
| `AI_BRIDGE_DEBUG` | `false` | Mode debug (log SQL queries) |

## Menambah Modul Baru

Untuk menambahkan modul baru (misal: Attendance, Leave):

1. Buat file query di `app/tools/` (misal: `attendance.py`)
2. Tambahkan pattern intent di `app/agents/intent_detector.py`
3. Update `app/agents/hris_agent.py` untuk memanggil tool baru
