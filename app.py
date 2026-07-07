import sys
import os
import json
import threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import messagebox, ttk, simpledialog
import requests
import keyboard
import pywinauto

class AgentApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Desktop Agent")
        self.root.geometry("700x750")
        
        self.is_running = False
        self.stop_requested = False
        
        self.setup_ui()
        self.setup_hotkey()

    def setup_ui(self):
        warning_frame = ttk.Frame(self.root, padding=10)
        warning_frame.pack(fill="x", padx=10, pady=5)

        warning_label = tk.Label(
            warning_frame,
            text="EMERGENCY: Press Ctrl+Space to abort execution",
            fg="#cc0000",
            font=("Segoe UI", 10, "bold"),
            bg="#ffdddd"
        )
        warning_label.pack(fill="x", pady=5)

        form_frame = ttk.Frame(self.root, padding=(6, 6))
        form_frame.pack(fill="both", expand=True, padx=10, pady=5)

        tk.Label(form_frame, text="OpenRouter API key:").pack(anchor="w")
        self.key_entry = tk.Entry(form_frame, show="*")
        self.key_entry.pack(fill="x", pady=2)

        tk.Label(form_frame, text="Model name:").pack(anchor="w")
        self.model_entry = tk.Entry(form_frame)
        self.model_entry.insert(0, "poolside/laguna-xs-2.1:free")
        self.model_entry.pack(fill="x", pady=2)

        tk.Label(form_frame, text="System prompt:").pack(anchor="w")
        self.prompt_text = tk.Text(form_frame, height=8)
        default_prompt = (
            "You are a Windows system administration agent. You have access to local tools to solve issues.\n"
            "Analyze the user problem and call the correct tool. Always explain your intent before running tools.\n"
            "If you complete the task or fail completely, inform the user about the actions taken.\n"
            "Before you do anything that cannot be easily undone, ask the user for confirmation using the 'ask_user' tool.\n"
            "If you need to run commands that require elevated privileges, use the 'escalate_privileges' tool.\n"
            "If you need to interact with the user interface, use 'get_ui_elements' to discover windows and elements, and 'interact_element' to click or focus them.\n"
            "If you need to input text, use the 'type_text' tool. If you need to run shell commands, use the 'run_command' tool.\n"
            "If you need to ask the user a question, use the 'ask_user' tool. Always provide clear instructions and feedback to the user.\n"
            "You must always provide clear instructions and feedback to the user. If you encounter an error, log it and inform the user.\n"
            "If you are unsure about what to do, ask the user for clarification using the 'ask_user' tool.\n"
            "If you need the user to google something for you, ask them to do so using the 'ask_user' tool."
            "Only use the ask user tool if you need it. If you can get the information you need via a command or the ui tools, do that instead. Only ask the user for information if you have no other way to get it."
            "Do not stop working until the problem is resolved and the user has confirmed they are satisifed or until you have exhausted all options and cannot resolve the issue. If you cannot resolve the issue, inform the user and provide a summary of what you tried."
            "Do not run any commands which block forever or require user input. If you need to run a command which requires user input, use the 'ask_user' tool to ask the user for the input and then run the command with the provided input. only if there is no other way. Anything else is prefered. If you need a blocking command such as running a process such as explorer which wont close use a command to execute a shell to detach run it and close so that you dont block."
            "If a command times out do not retry it. ask the user what they see if you need to."
            "if something is not as you expect or dosent work try another way and if it still dosent work or is not as expected ask the user."
        )
        self.prompt_text.insert("1.0", default_prompt)
        self.prompt_text.pack(fill="x", pady=2)

        tk.Label(form_frame, text="Describe the issue to resolve:").pack(anchor="w")
        self.issue_text = tk.Text(form_frame, height=5)
        self.issue_text.pack(fill="x", pady=2)

        self.btn_run = tk.Button(form_frame, text="Start Resolution Loop", command=self.start_loop_thread, bg="#ddffdd")
        self.btn_run.pack(fill="x", pady=10)

        tk.Label(form_frame, text="Execution activity logs:").pack(anchor="w")
        self.log_text = tk.Text(form_frame, height=12, state="disabled", bg="#f0f0f0")
        self.log_text.pack(fill="both", expand=True, pady=2)

    def setup_hotkey(self):
        try:
            keyboard.add_hotkey("ctrl+space", self.trigger_emergency_stop)
        except Exception as e:
            # Non-fatal: continue without hotkey but inform user
            self.write_log(f"⚠️ hotkey registration failed: {e}")

    def trigger_emergency_stop(self):
        if self.is_running:
            self.stop_requested = True
            self.write_log("🛑 EMERGENCY STOP TRIGGERED BY USER VIA HOTKEY!")

    def write_log(self, message):
        def _append():
            try:
                self.log_text.config(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
            except Exception:
                pass

        # Ensure UI updates happen on the main thread
        # Print to terminal for exact tracing as well
        try:
            print(message)
        except Exception:
            pass

        try:
            if threading.current_thread() is threading.main_thread():
                _append()
            else:
                self.root.after(0, _append)
        except Exception:
            try:
                self.root.after(0, _append)
            except Exception:
                pass

    def start_loop_thread(self):
        if self.is_running:
            messagebox.showwarning("active process", "the agent loop is already running.")
            return
        self.is_running = True
        self.stop_requested = False
        self.btn_run.config(state="disabled")
        threading.Thread(target=self.agent_loop, daemon=True).start()

    def agent_loop(self):
        api_key = self.key_entry.get().strip()
        model = self.model_entry.get().strip()
        system_prompt = self.prompt_text.get("1.0", "end").strip()
        user_issue = self.issue_text.get("1.0", "end").strip()

        if not api_key or not user_issue:
            self.write_log("❌ error: missing api key or issue description.")
            self.is_running = False
            self.root.after(0, lambda: self.btn_run.config(state="normal"))
            return

        self.write_log("🚀 starting diagnostic agent loop...")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"The user needs help with this issue: {user_issue}"}
        ]

        tools_schema = [
            {
                "name": "get_ui_elements",
                "description": "returns a structural list of active desktop window titles and elements via accessibility backend."
            },
            {
                "name": "interact_element",
                "description": "clicks or focuses a specific visual element on the screen using window titles and target identifiers.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "window_title": {"type": "string"},
                        "element_name": {"type": "string"},
                        "action": {"type": "string", "enum": ["click", "focus", "select"]}
                    },
                    "required": ["window_title", "element_name", "action"]
                }
            },
            {
                "name": "type_text",
                "description": "inputs text into the current active window layer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"}
                    },
                    "required": ["text"]
                }
            },
            {
                "name": "run_command",
                "description": "executes a shell command via a local cmd instance and returns console text output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"}
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "escalate_privileges",
                "description": "attempts to restart the application interface with elevated local administrator permissions via standard uac prompt."
            },
            {
                "name": "restart_explorer",
                "description": "restarts the Windows Explorer process (taskbar, desktop)."
            },
            {
                "name": "exec_python",
                "description": "executes Python code in an isolated subprocess and returns stdout/stderr. Times out after 30 seconds.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"}
                    },
                    "required": ["code"]
                }
            },
            {
                "name": "read_file",
                "description": "reads up to a configurable number of bytes from a text file and returns the content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer"},
                        "encoding": {"type": "string"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "read_file_bytes",
                "description": "reads a specific byte range from a file (binary mode).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "length": {"type": "integer"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "read_file_chars",
                "description": "reads a specific number of characters from a text file starting at an optional offset.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "count": {"type": "integer"},
                        "encoding": {"type": "string"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "read_file_lines",
                "description": "reads a specific number of lines from a text file starting at an optional line number (1-indexed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "num_lines": {"type": "integer"},
                        "encoding": {"type": "string"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "writes text to a file. Creates directories if needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "mode": {"type": "string"},
                        "encoding": {"type": "string"},
                        "create_dirs": {"type": "boolean"}
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "ask_user",
                "description": "displays a modal input popup to ask the user a text question when blocking choices emerge.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"}
                    },
                    "required": ["question"]
                }
            }
        ]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        while not self.stop_requested:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": [{"type": "function", "function": t} for t in tools_schema]
                }
                
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=45
                )
                
                if response.status_code != 200:
                    self.write_log(f"❌ server returned connection error code: {response.status_code}")
                    break
                
                data = response.json()
                # Defensive parsing of model response
                choice = {}
                try:
                    choice = data.get("choices", [{}])[0].get("message", {})
                except Exception:
                    choice = {}

                content = choice.get("content") if isinstance(choice, dict) else None
                if content:
                    # Log assistant content both to UI and terminal
                    self.write_log(f"🤖 agent thought: {content}")
                    try:
                        print("=== RAW ASSISTANT MESSAGE ===")
                        print(json.dumps(choice, indent=2, ensure_ascii=False))
                        print("=== END ASSISTANT MESSAGE ===")
                    except Exception:
                        print(content)
                    messages.append({"role": "assistant", "content": content})

                tool_calls = choice.get("tool_calls") or choice.get("function_calls") or []
                if tool_calls:
                    for tool_call in tool_calls:
                        if self.stop_requested:
                            break
                        # accommodate a couple of possible function-call shapes
                        tool_name = None
                        tool_args = {}
                        tool_id = tool_call.get("id", "call_id")

                        # Print exact tool call JSON to terminal for auditing
                        try:
                            print("--- RAW TOOL CALL ---")
                            print(json.dumps(tool_call, indent=2, ensure_ascii=False))
                            print("--- END TOOL CALL ---")
                        except Exception:
                            pass

                        if isinstance(tool_call.get("function"), dict):
                            func = tool_call["function"]
                            tool_name = func.get("name") or func.get("function")
                            raw_args = func.get("arguments", {})
                        else:
                            tool_name = tool_call.get("name") or tool_call.get("function")
                            raw_args = tool_call.get("arguments", {})

                        # normalize arguments to dict
                        if isinstance(raw_args, str):
                            try:
                                tool_args = json.loads(raw_args)
                            except Exception:
                                tool_args = {}
                        elif isinstance(raw_args, dict):
                            tool_args = raw_args
                        else:
                            tool_args = {}

                        self.write_log(f"🛠️ invoking tool instrument: {tool_name}")
                        tool_output = self.execute_tool(tool_name, tool_args)

                        # print exact tool output to terminal
                        try:
                            print("+++ TOOL OUTPUT +++")
                            # tool_output may be a JSON string or plain string
                            try:
                                parsed = json.loads(tool_output)
                                print(json.dumps(parsed, indent=2, ensure_ascii=False))
                            except Exception:
                                print(tool_output)
                            print("+++ END TOOL OUTPUT +++")
                        except Exception:
                            pass
                        
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "name": tool_name,
                            "content": str(tool_output)
                        })
                else:
                    self.write_log("✅ target loop completed or no more operational steps specified.")
                    break
                    
            except Exception as loop_error:
                self.write_log(f"❌ runtime error inside loop framework: {str(loop_error)}")
                break

        self.is_running = False
        self.root.after(0, lambda: self.btn_run.config(state="normal"))
        self.write_log("🏁 loop thread processing terminated.")

    def execute_tool(self, name, args):
        if name == "get_ui_elements":
            try:
                backend_desktop = pywinauto.Desktop(backend="uia")
                windows_discovered = backend_desktop.windows()
                elements_summary = []
                for win in windows_discovered[:20]:
                    try:
                        elements_summary.append(f"window title: {win.window_text()}")
                    except Exception:
                        elements_summary.append("window: <unreadable title>")
                return json.dumps({"active_windows": elements_summary})
            except Exception as ui_error:
                return json.dumps({"error": str(ui_error)})

        elif name == "interact_element":
            try:
                title = args.get("window_title")
                elem_name = args.get("element_name")
                action_type = args.get("action")
                
                backend_desktop = pywinauto.Desktop(backend="uia")
                target_window = backend_desktop.window(title_re=title)
                target_window.set_focus()
                
                element_hook = target_window.child_window(title=elem_name)
                if action_type == "click":
                    element_hook.click_input()
                elif action_type == "focus":
                    element_hook.set_focus()
                elif action_type == "select":
                    element_hook.select()
                return json.dumps({"status": "action executed successfully"})
            except Exception as element_error:
                return json.dumps({"error": str(element_error)})

        elif name == "type_text":
            try:
                text_to_input = args.get("text")
                # Echo exact typed text to terminal for tracing
                try:
                    print(f"[TYPE_TEXT] {text_to_input}")
                except Exception:
                    pass
                keyboard.write(text_to_input or "")
                return json.dumps({"status": "text layout injected"})
            except Exception as input_error:
                return json.dumps({"error": str(input_error)})

        elif name == "run_command":
            try:
                cmd = args.get("command")
                # Start process without blocking; allow up to 30s to collect output
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )

                try:
                    stdout, stderr = proc.communicate(timeout=30)
                    return json.dumps({
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": proc.returncode,
                        "timed_out": False,
                        "pid": proc.pid
                    })
                except subprocess.TimeoutExpired as te:
                    # Partial output may be available on the exception
                    stdout = te.output if hasattr(te, 'output') and te.output is not None else ""
                    stderr = te.stderr if hasattr(te, 'stderr') and te.stderr is not None else ""
                    # Do NOT kill the process; leave it running in background.
                    return json.dumps({
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": None,
                        "timed_out": True,
                        "running": True,
                        "pid": proc.pid
                    })
            except Exception as cmd_error:
                return json.dumps({"error": str(cmd_error)})

        elif name == "restart_explorer":
            try:
                # Kill explorer and restart it. This will affect user's desktop and taskbar.
                kill = subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                # Start explorer again
                proc = subprocess.Popen(["explorer.exe"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                return json.dumps({
                    "kill_stdout": kill.stdout,
                    "kill_stderr": kill.stderr,
                    "restart_pid": proc.pid,
                    "status": "restarted"
                })
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "exec_python":
            try:
                code = args.get("code", "")
                import tempfile
                import os

                # Write code to a temporary file to run isolated
                tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
                tf.write(code)
                tf.flush()
                tf_name = tf.name
                tf.close()

                try:
                    proc = subprocess.Popen([sys.executable, tf_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        stdout, stderr = proc.communicate(timeout=30)
                        return json.dumps({
                            "stdout": stdout,
                            "stderr": stderr,
                            "exit_code": proc.returncode,
                            "timed_out": False,
                            "pid": proc.pid
                        })
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            stdout, stderr = proc.communicate(timeout=5)
                        except Exception:
                            stdout, stderr = "", "" 
                        return json.dumps({
                            "stdout": stdout,
                            "stderr": stderr,
                            "exit_code": None,
                            "timed_out": True,
                            "killed": True,
                            "pid": proc.pid
                        })
                finally:
                    try:
                        os.unlink(tf_name)
                    except Exception:
                        pass
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "read_file":
            try:
                path = args.get("path")
                max_bytes = int(args.get("max_bytes", 100000))
                encoding = args.get("encoding", "utf-8")
                if max_bytes < 0:
                    max_bytes = 0
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    data = f.read(max_bytes)
                return json.dumps({"content": data, "size": len(data)})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "read_file_bytes":
            try:
                path = args.get("path")
                offset = int(args.get("offset", 0))
                length = int(args.get("length", 4096))
                if offset < 0:
                    offset = 0
                if length < 0:
                    length = 0
                with open(path, "rb") as f:
                    f.seek(offset)
                    data = f.read(length)
                # return as base64 to keep JSON safe for binary
                import base64
                b64 = base64.b64encode(data).decode("ascii")
                return json.dumps({"base64": b64, "bytes_read": len(data), "pid": os.getpid()})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "read_file_chars":
            try:
                path = args.get("path")
                offset = int(args.get("offset", 0))
                count = int(args.get("count", 4096))
                encoding = args.get("encoding", "utf-8")
                if offset < 0:
                    offset = 0
                if count < 0:
                    count = 0
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    if offset:
                        f.seek(offset)
                    data = f.read(count)
                return json.dumps({"content": data, "chars_read": len(data)})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "read_file_lines":
            try:
                path = args.get("path")
                start = int(args.get("start_line", 1))
                num = int(args.get("num_lines", 100))
                encoding = args.get("encoding", "utf-8")
                if start < 1:
                    start = 1
                if num < 0:
                    num = 0
                lines_out = []
                with open(path, "r", encoding=encoding, errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        if i < start:
                            continue
                        if len(lines_out) >= num:
                            break
                        lines_out.append(line.rstrip("\n"))
                return json.dumps({"lines": lines_out, "returned": len(lines_out)})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "write_file":
            try:
                path = args.get("path")
                content = args.get("content", "")
                mode = args.get("mode", "w")
                encoding = args.get("encoding", "utf-8")
                create_dirs = bool(args.get("create_dirs", False))
                folder = os.path.dirname(path)
                if folder and create_dirs:
                    os.makedirs(folder, exist_ok=True)
                with open(path, mode, encoding=encoding, errors="replace") as f:
                    f.write(content)
                return json.dumps({"status": "written", "path": path, "bytes": len(content)})
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif name == "escalate_privileges":
            try:
                try:
                    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
                except Exception:
                    is_admin = False

                if is_admin:
                    return json.dumps({"status": "already running with administrative clearance"})

                self.write_log("🔑 requesting elevated permissions (UAC)...")
                # Relaunch the current Python executable with admin rights
                params = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
                ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
                self.root.after(0, self.root.destroy)
                return json.dumps({"status": "escalation initiated; closing current process"})
            except Exception as escalation_error:
                return json.dumps({"error": str(escalation_error)})

        elif name == "ask_user":
            user_question = args.get("question")
            self.write_log(f"❓ agent is prompting a question: {user_question}")
            result_container = []

            def prompt():
                answer = simpledialog.askstring("Agent Question", user_question or "", parent=self.root)
                result_container.append(answer if answer is not None else "")

            # Run the prompt on the main thread and wait
            self.root.after(0, prompt)
            import time
            while not result_container:
                if self.stop_requested:
                    return json.dumps({"status": "interrupted by stop command"})
                time.sleep(0.1)

            return json.dumps({"user_response": result_container[0]})

        return json.dumps({"error": "specified tool routine could not be located"})

if __name__ == "__main__":
    app_window = tk.Tk()
    application_instance = AgentApp(app_window)
    app_window.mainloop()