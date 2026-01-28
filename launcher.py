import subprocess
import sys
import time
from app.core.config import settings

def run_service(command, title):
    print(f"Starting {title}...")
    try:
        # Use Popen to run in background (or new window on Windows)
        if sys.platform == "win32":
            subprocess.Popen(f"start \"{title}\" {command}", shell=True)
        else:
            # Linux/Mac simple background
            subprocess.Popen(command, shell=True)
        print(f"{title} started.")
    except Exception as e:
        print(f"Failed to start {title}: {e}")

def main():
    print("===================================================")
    print(f"       {settings.APP_NAME} - Launcher")
    print("===================================================")
    
    # 1. Backend
    # Use sys.executable to ensure we use the same python interpreter
    python_exe = sys.executable
    backend_cmd = f'"{python_exe}" -m uvicorn app.main:app --reload --host {settings.HOST} --port {settings.BACKEND_PORT}'
    run_service(backend_cmd, f"BtB Backend API (Port {settings.BACKEND_PORT})")
    
    time.sleep(2) # Wait a bit for backend

    # 2. Admin
    # Correct path based on file structure
    admin_cmd = f'"{python_exe}" -m streamlit run app/web/pages/Admin_Dashboard.py --server.port {settings.ADMIN_PORT} --server.address {settings.HOST}'
    run_service(admin_cmd, f"BtB Admin Dashboard (Port {settings.ADMIN_PORT})")

    # 3. Chat UI
    # chat_ui.py is the main entry, pages are automatically discovered if in 'pages' subdir relative to main
    chat_cmd = f'"{python_exe}" -m streamlit run app/web/chat_ui.py --server.port {settings.CHAT_PORT} --server.address {settings.HOST}'
    run_service(chat_cmd, f"BtB Chat Interface (Port {settings.CHAT_PORT})")

    print("\nAll services initiated.")
    print(f"- API Docs:      http://{settings.HOST}:{settings.BACKEND_PORT}/docs")
    print(f"- Admin Panel:   http://{settings.HOST}:{settings.ADMIN_PORT}")
    print(f"- Chat UI:       http://{settings.HOST}:{settings.CHAT_PORT}")
    print("\nPress any key to exit launcher (services will keep running)...")
    input()

if __name__ == "__main__":
    main()
