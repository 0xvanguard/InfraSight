import time
import requests
import psutil
import socket
import json

API_URL = "http://localhost:8001/api/v1/metrics"
HOSTNAME = socket.gethostname()
API_KEY = "infrasight-agent-secret"

def collect_metrics():
    # CPU
    cpu_percent = psutil.cpu_percent(interval=1)
    
    # RAM
    mem = psutil.virtual_memory()
    ram_percent = mem.percent
    
    # Disk
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    
    # Health Score Logic (Simple)
    score = 100
    if cpu_percent > 85: score -= 20
    elif cpu_percent > 70: score -= 10
    
    if ram_percent > 90: score -= 20
    elif ram_percent > 80: score -= 10
    
    if disk_percent > 90: score -= 30
    
    score = max(0, score)
    status = "HEALTHY"
    if score < 70: status = "WARNING"
    if score < 40: status = "CRITICAL"
    
    return {
        "hostname": HOSTNAME,
        "cpu_usage": cpu_percent,
        "ram_usage": ram_percent,
        "disk_usage": disk_percent,
        "health_score": score,
        "status": status,
        "services": {"sshd": "running", "docker": "running"} # Simulated
    }

def send_metrics(payload):
    try:
        headers = {"X-Agent-Token": API_KEY}
        response = requests.post(API_URL, json=payload, headers=headers)
        if response.status_code == 200:
            print(f"[{time.strftime('%X')}] Telemetry sent. Status: {payload['status']} | Score: {payload['health_score']}")
        else:
            print(f"Failed to send: {response.text}")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    print(f"Starting InfraSight Light Agent on {HOSTNAME}...")
    while True:
        data = collect_metrics()
        send_metrics(data)
        time.sleep(5)
