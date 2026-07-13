import os
import glob
import logging
import threading
import time
import subprocess

logger = logging.getLogger("FSWatcher")

# List of files/globs we want to watch
WATCH_PATTERNS = [
    "/containers/**/docker-compose.yaml",
    "/containers/webservices/caddy/Caddyfile"
]

# Scripts to execute on change
GENERATE_SCRIPTS = [
    ["python3", "/containers/webservices/webdomain/www/generate_services.py"],
    ["python3", "/containers/scripts/generate_catalog.py"],
    ["python3", "/containers/dev/caddy-auth-portal/parser.py"]
]

def run_regeneration():
    logger.info("Change detected in configurations. Running portal & catalog regeneration scripts...")
    for cmd in GENERATE_SCRIPTS:
        try:
            logger.info(f"Running: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                logger.error(f"Script failed with code {res.returncode}. Stderr: {res.stderr}")
            else:
                logger.info(f"Script succeeded.")
        except Exception as e:
            logger.error(f"Error running regeneration script {' '.join(cmd)}: {e}")

def get_watched_files():
    files = []
    for pattern in WATCH_PATTERNS:
        if "**" in pattern:
            matched = glob.glob(pattern, recursive=True)
        else:
            matched = glob.glob(pattern)
        files.extend(matched)
    return sorted(list(set([f for f in files if os.path.isfile(f)])))

def watch_loop():
    logger.info("Initializing configuration file watcher...")
    last_mtimes = {}
    try:
        for f in get_watched_files():
            last_mtimes[f] = os.path.getmtime(f)
    except Exception as e:
        logger.error(f"Error reading initial file modification times: {e}")

    # Main watch loop
    while True:
        try:
            time.sleep(5)  # Poll filesystem every 5 seconds
            current_files = get_watched_files()
            has_changes = False

            # Check for modified or new files
            for f in current_files:
                current_mtime = os.path.getmtime(f)
                if f not in last_mtimes:
                    logger.info(f"New configuration file detected: {f}")
                    last_mtimes[f] = current_mtime
                    has_changes = True
                elif last_mtimes[f] < current_mtime:
                    logger.info(f"Configuration file change detected: {f}")
                    last_mtimes[f] = current_mtime
                    has_changes = True

            # Check for deleted files
            for f in list(last_mtimes.keys()):
                if f not in current_files:
                    logger.info(f"Configuration file deleted: {f}")
                    del last_mtimes[f]
                    has_changes = True

            if has_changes:
                run_regeneration()

        except Exception as e:
            logger.error(f"Error in watcher loop: {e}")

def start_fswatcher_thread():
    t = threading.Thread(target=watch_loop, daemon=True, name="FSWatcher")
    t.start()
    logger.info("Configuration File Watcher thread started.")
