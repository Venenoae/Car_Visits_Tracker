# Vehicle Visits Tracker

An intelligent vehicle entry and exit tracking system designed for a vehicle care workshop with two zones (Ground Floor & Basement). The system captures vehicle snapshots at gates via Raspberry Pis, automatically recognizes License Plates, Colors, and Brands using self-hosted AI models (YOLOv8 + EasyOCR), and streams live dashboard updates via WebSockets.

---

## Workspace Directory Structure

```text
Car_Visits_Tracker/
├── implementation_plan.md   # Detailed design plan
├── task.md                  # Development checklist
├── README.md                # Project context and developer guide (This file)
│
├── backend/                 # FastAPI Python backend & AI Engine
│   ├── main.py              # Application entry point
│   ├── requirements.txt     # Python dependencies
│   ├── database.py          # MySQL connection and models
│   ├── auth.py              # User authentication (JWT)
│   ├── ai_pipeline.py       # YOLOv8 + EasyOCR processing
│   ├── schema.sql           # Database schema migrations
│   └── uploads/             # Stores captured snapshots
│
├── frontend/                # React Vite Dashboard
│   ├── src/                 # Component source code
│   ├── package.json         # Node.js dependencies
│   └── vite.config.ts       # Vite config
│
└── edge/                    # Edge device code
    ├── edge_tracker.py      # Raspberry Pi OpenCV capture script
    ├── test_sender.py       # Windows simulator script for local testing
    └── test_images/         # Mock images for the simulator
```

---

## Local Development Quick Start (Windows Laptop)

### 1. Database Setup
1. Start your local MySQL server (XAMPP / Docker / MySQL Community Server).
2. Create a new database named `car_visits_tracker`.
3. Import the `backend/schema.sql` to create the tables.

### 2. Backend Setup
1. Navigate to the `backend/` directory:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the FastAPI development server:
   ```bash
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

### 3. Frontend Setup
1. Navigate to the `frontend/` directory:
   ```bash
   cd ../frontend
   ```
2. Install Node.js packages:
   ```bash
   npm install
   ```
3. Run the frontend development server:
   ```bash
   npm run dev
   ```
4. Open your browser to `http://localhost:5173`.

### 4. Running the Simulation
1. Place standard images of vehicles with visible plates in the `edge/test_images/` directory.
2. Run the simulator script:
   ```bash
   python edge/test_sender.py
   ```
3. Observe the logs of plates being parsed and the frontend dashboard updating dynamically in real-time.

---

## Production & Cloud Migration Guide

Once local testing on your Windows laptop is complete, migrate the system online using the following steps:

### 1. Database Migration
1. Set up a secure MySQL instance on your cloud provider (e.g. AWS RDS or a managed database on DigitalOcean).
2. Export your local database schema:
   ```bash
   mysqldump -u root -p car_visits_tracker > db_backup.sql
   ```
3. Import the schema into your cloud MySQL database:
   ```bash
   mysql -h <CLOUD_DB_HOST> -u <CLOUD_USER> -p <CLOUD_DB_NAME> < db_backup.sql
   ```

### 2. Cloud Server Deployment (FastAPI Backend & AI)
1. Provision a VPS (e.g., Ubuntu 22.04 LTS, 4GB+ RAM, 2 vCPUs) to run your backend and AI models.
2. Install Python, virtual environment tools, and Git:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git nginx
   ```
3. Clone this repository onto the cloud server.
4. Create a production `.env` file containing:
   * Production MySQL connection credentials
   * A strong, random key for `SECRET_KEY`
5. Create and run a systemd service to keep the FastAPI application running continuously:
   ```ini
   # /etc/systemd/system/callmycar.service
   [Unit]
   Description=FastAPI CallMyCar Backend Service
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/Car_Visits_Tracker/backend
   ExecStart=/home/ubuntu/Car_Visits_Tracker/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
6. Start and enable the service:
   ```bash
   sudo systemctl enable callmycar --now
   ```

### 3. Nginx Reverse Proxy & SSL Setup
1. Configure Nginx to forward external HTTP requests to your local FastAPI server.
2. Create an Nginx site config:
   ```nginx
   # /etc/nginx/sites-available/callmycar
   server {
       server_name api.yourdomain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
       }

       location /static/uploads/ {
           alias /home/ubuntu/Car_Visits_Tracker/backend/uploads/;
       }
   }
   ```
3. Enable the config and reload Nginx:
   ```bash
   sudo ln -s /etc/nginx/sites-available/callmycar /etc/nginx/sites-enabled/
   sudo systemctl reload nginx
   ```
4. Secure the server with SSL (HTTPS) using Certbot:
   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d api.yourdomain.com
   ```

### 4. Frontend Deployment
1. Update `API_BASE` and `WS_URL` in `frontend/src/App.tsx` to point to your cloud domain (`https://api.yourdomain.com/api` and `wss://api.yourdomain.com/ws`).
2. Build the production React bundle:
   ```bash
   cd frontend
   npm run build
   ```
3. Deploy the compiled static folder (`frontend/dist/`) to a static hosting provider (e.g., Netlify, Vercel, or AWS S3 + CloudFront) or host it directly via Nginx.

### 5. Raspberry Pi Update
1. Update the `API_URL` configuration inside `edge/edge_tracker.py` on your Raspberry Pi devices to point to your cloud domain:
   ```python
   API_URL = "https://api.yourdomain.com/api/capture"
   ```
2. Start the `edge_tracker.py` script on your Pis. The edge caches will automatically start streaming capture frames online!

