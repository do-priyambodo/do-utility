import sys
import os
import shutil
import traceback
from datetime import datetime

class TeeLogger:
    def __init__(self, filepath, terminal):
        self.terminal = terminal
        self.log = open(filepath, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
        if message.strip() and ("❌" in message or "Error" in message or "failed" in message.lower() or "exception" in message.lower()):
            # Extract log directory path dynamically
            log_dir = "log"
            if not os.path.exists(log_dir) and os.path.exists("../log"):
                log_dir = "../log"
            os.makedirs(log_dir, exist_ok=True)
            filepath = os.path.join(log_dir, "error.log")
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {message.strip()}\n")

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def backup_old_logs():
    log_dir = "log"
    # If the script is running from a subdirectory like prereq/, adjust log directory
    if not os.path.exists(log_dir) and os.path.exists("../log"):
        log_dir = "../log"
    elif not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for log_name in ["setup.log", "error.log", "cloud.log"]:
        path = os.path.join(log_dir, log_name)
        if os.path.exists(path):
            backup_path = os.path.join(log_dir, f"{log_name}.{timestamp}")
            shutil.move(path, backup_path)

def log_error(message):
    log_dir = "log"
    if not os.path.exists(log_dir) and os.path.exists("../log"):
        log_dir = "../log"
    os.makedirs(log_dir, exist_ok=True)
    filepath = os.path.join(log_dir, "error.log")
    with open(filepath, "a", encoding="utf-8") as f:
        timestamp = datetime.now().isoformat()
        f.write(f"[{timestamp}] {message}\n")

def log_cloud(content):
    log_dir = "log"
    if not os.path.exists(log_dir) and os.path.exists("../log"):
        log_dir = "../log"
    os.makedirs(log_dir, exist_ok=True)
    filepath = os.path.join(log_dir, "cloud.log")
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(content + "\n")

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Format the traceback
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = "".join(tb_lines)
    
    # Log to error.log
    log_error(f"Uncaught Exception:\n{tb_text}")
    
    # Print it to original stderr
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def init_logging(log_type="setup"):
    # Perform backup of old files on initialization
    backup_old_logs()
    
    log_dir = "log"
    if not os.path.exists(log_dir) and os.path.exists("../log"):
        log_dir = "../log"
    
    # Set sys excepthook for uncaught errors
    sys.excepthook = handle_exception
    
    if log_type == "setup":
        filepath = os.path.join(log_dir, "setup.log")
        sys.stdout = TeeLogger(filepath, sys.stdout)
        sys.stderr = TeeLogger(filepath, sys.stderr)
