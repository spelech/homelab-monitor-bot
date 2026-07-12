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
    print("  python3 cli.py test-prompt --target <id> --error <log_or_file> [--history <cmd>]")
    print("                                      - Test SRE prompts against agy live and validate output")
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
    elif cmd == "test-prompt":
        import argparse
        import time
        import subprocess
        import re
        import json
        
        parser = argparse.ArgumentParser(description="Test SRE prompts against agy")
        parser.add_argument("--target", required=True, help="Mock target ID (e.g. kopia)")
        parser.add_argument("--error", required=True, help="Error logs (string or path to log file)")
        parser.add_argument("--history", default="", help="Optional mock successful historical command")
        
        args = parser.parse_args(sys.argv[2:])
        
        target_id = args.target
        error_input = args.error
        
        if os.path.exists(error_input):
            with open(error_input, "r") as f:
                error_logs = f.read()
        else:
            error_logs = error_input
            
        historical_context = ""
        if args.history:
            historical_context = (
                f"\n\nHistorical context: In the past, a similar issue on this container "
                f"was successfully fixed using this command: {args.history}. "
                f"Take this into consideration when proposing your fix."
            )
            
        prompt = (
            f"Container failure detected on '{target_id}'.\n"
            f"Error Logs:\n{error_logs}{historical_context}\n\n"
            "You are an SRE bot. Focus strictly on diagnosing this container failure by inspecting its configuration, files, and Docker logs. "
            "Do NOT research, grep, or search for the 'agy' command or its flags (like --dangerously-skip-permissions) on the system. "
            "Output ONLY valid JSON with exactly three keys: "
            "'root_cause' (a string explaining the issue), "
            "'proposed_fix' (a string containing valid bash commands to fix it), and "
            "'category' (a string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'). "
            "Do not include markdown formatting or backticks."
        )
        
        print("\n" + "="*80)
        print("GENERATED PROMPT:")
        print("="*80)
        print(prompt)
        print("="*80)
        
        from app.investigator import AGY_PATH
        print(f"\nRunning agy at {AGY_PATH}...")
        start_time = time.time()
        
        try:
            result = subprocess.run(
                [AGY_PATH, "--print", "--dangerously-skip-permissions", prompt],
                capture_output=True,
                text=True,
                timeout=180
            )
            duration = time.time() - start_time
            print(f"Command completed in {duration:.2f} seconds.")
            
            if result.returncode != 0:
                print(f"ERROR: agy returned non-zero exit code {result.returncode}")
                print(f"Stderr:\n{result.stderr}")
                sys.exit(1)
                
            output = result.stdout
            print("\n" + "="*80)
            print("RAW AGY OUTPUT:")
            print("="*80)
            print(output)
            print("="*80)
            
            json_match = re.search(r"\{.*\}", output, re.DOTALL)
            if not json_match:
                print("\n❌ VALIDATION FAILED: No JSON block found in output.")
                sys.exit(1)
                
            clean_json_str = json_match.group(0)
            try:
                data = json.loads(clean_json_str)
                print("\n✅ VALIDATION PASSED: Successfully parsed JSON.")
                print(f"  Category:     {data.get('category')}")
                print(f"  Root Cause:   {data.get('root_cause')}")
                print(f"  Proposed Fix: {data.get('proposed_fix')}")
            except Exception as parse_err:
                print(f"\n❌ VALIDATION FAILED: JSON syntax error: {parse_err}")
                print(f"Extracted block:\n{clean_json_str}")
                sys.exit(1)
                
        except subprocess.TimeoutExpired:
            print("\n❌ ERROR: agy command timed out after 3 minutes.")
            sys.exit(1)
        except Exception as run_err:
            print(f"\n❌ ERROR: Failed to run agy: {run_err}")
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
