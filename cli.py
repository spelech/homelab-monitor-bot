#!/usr/bin/env python3
import sys
import os

# Set PYTHONPATH to current directory to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import init_db, get_setting, set_setting

# Run database initialization/migration
init_db()

def print_help():
    print("AutoHeal SRE MonitorBot CLI")
    print("Usage:")
    print("  python3 cli.py status               - View current silent mode and autopilot settings")
    print("  python3 cli.py silent [on/off]      - Enable or disable silent mode (monitoring only)")
    print("  python3 cli.py autopilot [on/off]   - Enable or disable autopilot mode (auto-execute fixes)")
    print("  python3 cli.py help                 - Show this help message")

def main():
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "help":
        print_help()
    elif cmd == "status":
        silent = get_setting("silent_mode", "false")
        autopilot = get_setting("autopilot", "false")
        print(f"Silent Mode (Monitoring Only): {silent.upper()}")
        print(f"Autopilot (Auto-Fix):         {autopilot.upper()}")
    elif cmd == "silent":
        if len(sys.argv) < 3:
            print("Error: Specify 'on' or 'off'")
            sys.exit(1)
        val = sys.argv[2].lower()
        if val in ["on", "true", "yes"]:
            set_setting("silent_mode", "true")
            print("Silent Mode ENABLED (Monitoring Only, notifications and investigations paused)")
        elif val in ["off", "false", "no"]:
            set_setting("silent_mode", "false")
            print("Silent Mode DISABLED (Active notification and investigation enabled)")
        else:
            print("Error: Invalid value, use 'on' or 'off'")
            sys.exit(1)
    elif cmd == "autopilot":
        if len(sys.argv) < 3:
            print("Error: Specify 'on' or 'off'")
            sys.exit(1)
        val = sys.argv[2].lower()
        if val in ["on", "true", "yes"]:
            set_setting("autopilot", "true")
            print("Autopilot Mode ENABLED (AI proposed fixes will be automatically executed)")
        elif val in ["off", "false", "no"]:
            set_setting("autopilot", "false")
            print("Autopilot Mode DISABLED (AI proposed fixes require manual user approval)")
        else:
            print("Error: Invalid value, use 'on' or 'off'")
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
