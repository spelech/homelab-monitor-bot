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
    print("  python3 cli.py memory search <query> - Semantic search for past fixes in Qdrant")
    print("  python3 cli.py memory learn --target <id> --cause <text> --fix <cmd> [--id <uuid>]")
    print("                                      - Manually add a successful fix to Qdrant memory")
    print("  python3 cli.py memory list          - List all learned issues and commands in Qdrant")
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
                [AGY_PATH, "--dangerously-skip-permissions", "--print", prompt],
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
    elif cmd == "memory":
        if len(sys.argv) < 3:
            print("Error: Specify a memory subcommand: 'search', 'learn', or 'list'")
            sys.exit(1)
            
        subcmd = sys.argv[2].lower()
        from app.qdrant_mem import qdrant_mem
        
        if subcmd == "list":
            memories = qdrant_mem.list_memories()
            if not memories:
                print("No memories stored in Qdrant yet.")
            else:
                print(f"\n--- Learned Memories in Qdrant ({len(memories)} total) ---")
                for point in memories:
                    payload = point.payload or {}
                    print(f"\nID:       {point.id}")
                    print(f"Target:   {payload.get('target_id')} ({payload.get('target_type')})")
                    print(f"Fix Cmd:  {payload.get('successful_command')}")
                print("\n" + "-"*50)
                
        elif subcmd == "search":
            if len(sys.argv) < 4:
                print("Error: Provide a query string. e.g. python3 cli.py memory search \"port collision\"")
                sys.exit(1)
            query_text = " ".join(sys.argv[3:])
            results = qdrant_mem.semantic_search(query_text)
            if not results:
                print(f"No match found for: '{query_text}'")
            else:
                print(f"\n--- Semantic Search Results for: '{query_text}' ---")
                for match in results:
                    metadata = match.metadata or {}
                    print(f"\nScore:    {match.score:.4f}")
                    print(f"Target:   {metadata.get('target_id')}")
                    print(f"Fix Cmd:  {metadata.get('successful_command')}")
                print("\n" + "-"*50)
                
        elif subcmd == "learn":
            import argparse
            parser = argparse.ArgumentParser(description="Manually teach Qdrant a successful fix")
            parser.add_argument("--target", required=True, help="Target container/service name")
            parser.add_argument("--cause", required=True, help="Root cause description")
            parser.add_argument("--fix", required=True, help="Successful fix command")
            parser.add_argument("--id", default=None, help="Optional UUID for the memory")
            
            args = parser.parse_args(sys.argv[3:])
            import uuid
            mem_id = args.id or str(uuid.uuid4())
            
            success = qdrant_mem.learn_incident(
                incident_id=mem_id,
                target_id=args.target,
                root_cause=args.cause,
                proposed_fix=args.fix
            )
            if success:
                print(f"Successfully saved fix to memory! ID: {mem_id}")
            else:
                print("Error: Failed to save fix to Qdrant memory.")
        else:
            print(f"Unknown memory subcommand: {subcmd}")
            sys.exit(1)
    else:
        print(f"Unknown command: {cmd}")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
