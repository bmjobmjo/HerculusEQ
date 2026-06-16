import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import time
import os
import json
import sys
import websocket

def get_application_path():
    """Get the path to the application directory (works for dev and frozen/onefile)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class WebSocketTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.ws_app = None
        self.ws_thread = None
        self.is_connected = False
        self.pause_event = threading.Event()

        self.saving_file = None
        self.is_saving = False

        self.all_received_data = ""
        self.filter_text = ""

        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "websocket_commands.json")
        self.max_history = 500  # Increased limit
        self.load_command_history()

        self.settings_file = os.path.join(get_application_path(), "websocket_settings.json")
        
        self.create_widgets()
        self.load_settings()

    def create_widgets(self):
        # Frame for WebSocket Configuration
        config_frame = ttk.LabelFrame(self.frame, text="WebSocket Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        # WebSocket URI
        ttk.Label(config_frame, text="URI:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.uri_entry = ttk.Entry(config_frame, width=30)
        self.uri_entry.insert(0, "wss://echo.websocket.events")  # Default public echo WebSocket
        self.uri_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Connect/Disconnect Button
        self.connect_button = ttk.Button(config_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

        # Frame for Received Data
        received_frame = ttk.LabelFrame(self.frame, text="Received Data")
        received_frame.grid(row=0, column=1, rowspan=3, padx=10, pady=10, sticky="nsew")
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=0)
        self.frame.grid_rowconfigure(2, weight=0)

        self.received_text = scrolledtext.ScrolledText(received_frame, wrap=tk.WORD, state='disabled')
        self.received_text.pack(expand=True, fill="both", padx=5, pady=5)

        # Button Frame for Pause, Clear, and Filter
        button_filter_frame = ttk.Frame(received_frame)
        button_filter_frame.pack(pady=5, fill=tk.X)

        button_frame = ttk.Frame(button_filter_frame)
        button_frame.pack(side=tk.LEFT, padx=5)

        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = ttk.Button(button_frame, text="Clear", command=self.clear_received_text)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        filter_input_frame = ttk.Frame(button_filter_frame)
        filter_input_frame.pack(side=tk.RIGHT, padx=5, fill=tk.X, expand=True)
        ttk.Label(filter_input_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.filter_entry = ttk.Entry(filter_input_frame)
        self.filter_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.filter_entry.bind("<KeyRelease>", self.apply_filter)

        # Frame for Saving Data
        save_frame = ttk.LabelFrame(self.frame, text="Save Received Data")
        save_frame.grid(row=2, column=0, padx=10, pady=10, sticky="sw")

        ttk.Label(save_frame, text="Save Path:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.save_path_entry = ttk.Entry(save_frame, width=30)
        self.save_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = ttk.Button(save_frame, text="Browse", command=self.browse_save_path)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5)

        ttk.Label(save_frame, text="File Name:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.file_name_entry = ttk.Entry(save_frame, width=30)
        self.file_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        self.save_button = ttk.Button(save_frame, text="Start Saving", command=self.toggle_saving)
        self.save_button.grid(row=1, column=2, padx=5, pady=5)

        # Frame for Sending Data
        send_frame = ttk.LabelFrame(self.frame, text="Send Message")
        send_frame.grid(row=1, column=0, padx=10, pady=10, sticky="sw")

        self.send_combobox = ttk.Combobox(send_frame, width=37)
        self.send_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data())
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.send_button = ttk.Button(send_frame, text="Send", command=self.send_data)
        self.send_button.grid(row=0, column=1, padx=5, pady=5)

        self.edit_button = ttk.Button(send_frame, text="✎", width=3, command=self.open_big_edit_box)
        self.edit_button.grid(row=0, column=2, padx=5, pady=5)

        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=3, padx=5, pady=5)

        self.send_json_var = tk.BooleanVar()
        self.send_json_checkbox = ttk.Checkbutton(send_frame, text="Format as JSON", variable=self.send_json_var)
        self.send_json_checkbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Status Label
        self.status_label = ttk.Label(self.frame, text="", anchor="w")
        self.status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        self.update_combobox_values()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
                self.uri_entry.delete(0, tk.END)
                self.uri_entry.insert(0, settings.get("uri", ""))
            except Exception as e:
                print(f"Failed to load WebSocket settings: {e}")

    def save_settings(self):
        settings = {
            "uri": self.uri_entry.get().strip()
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save WebSocket settings: {e}")

    def on_combobox_key_release(self, event):
        pass

    def update_combobox_values(self, event=None):
        reversed_history = list(reversed(self.command_history))
        self.send_combobox['values'] = reversed_history

    def open_big_edit_box(self):
        edit_window = tk.Toplevel(self.frame)
        edit_window.title("Big Edit Box")
        edit_window.geometry("600x400")
        edit_window.transient(self.frame.winfo_toplevel())
        edit_window.grab_set()

        # Buttons (pack first to the window so they stay at the bottom)
        button_frame = ttk.Frame(edit_window, padding="10")
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        main_frame = ttk.Frame(edit_window, padding="10")
        main_frame.pack(expand=True, fill="both")

        # History selector
        history_frame = ttk.Frame(main_frame)
        history_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(history_frame, text="Select from History:").pack(side=tk.LEFT, padx=(0, 5))
        
        history_combo = ttk.Combobox(history_frame, state="readonly")
        history_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        reversed_history = list(reversed(self.command_history))
        history_combo['values'] = reversed_history
        
        # Text editing area
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(expand=True, fill="both")
        
        edit_text = tk.Text(text_frame, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=edit_text.yview)
        edit_text.configure(yscrollcommand=scrollbar.set)
        
        edit_text.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")
        
        # Insert current text from the small combobox
        current_text = self.send_combobox.get()
        edit_text.insert(tk.END, current_text)

        def on_history_select(event):
            selected = history_combo.get()
            if selected:
                edit_text.delete('1.0', tk.END)
                edit_text.insert(tk.END, selected)
                
        history_combo.bind("<<ComboboxSelected>>", on_history_select)

        # Text editing area
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(expand=True, fill="both")
        
        edit_text = tk.Text(text_frame, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=edit_text.yview)
        edit_text.configure(yscrollcommand=scrollbar.set)
        
        edit_text.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")
        
        def send_from_edit():
            msg = edit_text.get('1.0', tk.END).strip()
            if msg:
                # Put it back to combobox to use existing send_data logic
                self.send_combobox.set(msg)
                self.send_data()
                edit_window.destroy()
                
        ttk.Button(button_frame, text="Send", command=send_from_edit).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=edit_window.destroy).pack(side="left")

    def show_command_history(self):
        history_window = tk.Toplevel(self.frame)
        history_window.title("Command History")
        history_window.geometry("500x300")
        history_window.transient(self.frame.winfo_toplevel())
        history_window.grab_set()

        main_frame = ttk.Frame(history_window, padding="10")
        main_frame.pack(expand=True, fill="both")

        ttk.Label(main_frame, text="Recent Messages (most recent first):").pack(anchor="w", pady=(0, 5))

        # Buttons (pack first so they stay at the bottom)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, pady=(10, 0))

        ttk.Button(button_frame, text="Clear History", command=lambda: self.clear_command_history(history_window)).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=history_window.destroy).pack(side="left")

        listbox_frame = ttk.Frame(main_frame)
        listbox_frame.pack(expand=True, fill="both")

        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical")
        listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        scrollbar.config(command=listbox.yview)

        listbox.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")

        reversed_history = list(reversed(self.command_history))
        for cmd in reversed_history:
            listbox.insert(tk.END, cmd)
            
        def on_history_select(event):
            selection = listbox.curselection()
            if selection:
                index = selection[0]
                selected_cmd = listbox.get(index)
                self.send_combobox.set(selected_cmd)
                history_window.destroy()
                
        listbox.bind('<<ListboxSelect>>', on_history_select)

    def clear_command_history(self, window):
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all message history?", parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Message history has been cleared.")

    def load_command_history(self):
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
            except Exception as e:
                print(f"Failed to load message history: {e}")
                self.command_history = []

    def save_command_history(self):
        try:
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save message history: {e}")

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect_ws()
        else:
            self.connect_ws()

    def on_open(self, ws):
        self.notebook.winfo_toplevel().after(0, self.on_connection_success)

    def on_message(self, ws, message):
        try:
            if isinstance(message, bytes):
                message = message.decode('utf-8', errors='replace')
            timestamp = time.strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] [RECV] {message}\n"
            self.notebook.winfo_toplevel().after(0, self.process_received_message, formatted_message)
        except Exception as e:
            print(f"Error processing message: {e}")

    def on_error(self, ws, error):
        self.notebook.winfo_toplevel().after(0, self.on_connection_error, str(error))

    def on_close(self, ws, close_status_code, close_msg):
        self.notebook.winfo_toplevel().after(0, self.on_disconnect_gui, close_status_code, close_msg)

    def on_connection_success(self):
        self.is_connected = True
        self.connect_button.config(text="Disconnect")
        self.pause_button.config(state=tk.NORMAL)
        self.uri_entry.config(state="disabled")
        
        uri = self.uri_entry.get().strip()
        self.update_status(f"Connected to {uri}", "green")
        self.save_settings()

    def on_connection_error(self, error):
        if not hasattr(self, 'intentional_disconnect') or not self.intentional_disconnect:
            messagebox.showerror("WebSocket Error", f"WebSocket encountered an error:\n{error}")
            self.update_status(f"Error: {error}", "red")

    def on_disconnect_gui(self, close_status_code, close_msg):
        self.is_connected = False
        self.connect_button.config(text="Connect")
        self.pause_button.config(text="Pause", state=tk.DISABLED)
        self.uri_entry.config(state="normal")
        self.ws_app = None

        if hasattr(self, 'intentional_disconnect') and self.intentional_disconnect:
            self.update_status("Disconnected", "red")
            self.intentional_disconnect = False
        else:
            self.update_status(f"Disconnected (Code: {close_status_code})", "orange")
            
        if self.is_saving:
            self.toggle_saving()

    def connect_ws(self):
        uri = self.uri_entry.get().strip()
        if not uri:
            messagebox.showwarning("Connection Error", "Please enter a WebSocket URI.")
            return

        self. intentional_disconnect = False
        
        try:
            self.ws_app = websocket.WebSocketApp(
                uri,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Run the client in a background thread
            self.ws_thread = threading.Thread(target=self.ws_app.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
            self.pause_event.clear()
            self.update_status(f"Connecting to {uri}...", "orange")

        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to WebSocket:\n{e}")
            self.is_connected = False
            self.update_status("Connection failed", "red")

    def disconnect_ws(self):
        self.save_settings()
        self.intentional_disconnect = True
        if self.ws_app:
            self.ws_app.close()
            # on_close will handle UI cleanups

    def toggle_pause(self):
        if self.is_connected:
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.pause_button.config(text="Pause")
                if self.is_saving:
                    self.update_status(f"Connected & Saving (WebSocket)", "blue")
                else:
                    uri = self.uri_entry.get().strip()
                    self.update_status(f"Connected to {uri}", "green")
            else:
                self.pause_event.set()
                self.pause_button.config(text="Resume")
                self.update_status("Paused (WebSocket)", "orange")

    def process_received_message(self, message):
        if not self.pause_event.is_set():
            self.all_received_data += message
            self.apply_filter()

            if self.is_saving and self.saving_file:
                try:
                    self.saving_file.write(message)
                    self.saving_file.flush()
                except Exception as e:
                    print(f"Error writing to save file: {e}")
                    self.toggle_saving()
                    messagebox.showerror("Saving Error", f"Error writing to file:\n{e}\nSaving stopped.")

    def update_received_text(self, data):
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.insert(tk.END, data)
        self.received_text.see(tk.END)

    def clear_received_text(self):
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.config(state='disabled')
        self.all_received_data = ""
        self.filter_entry.delete(0, tk.END)
        self.filter_text = ""

    def browse_save_path(self):
        save_directory = filedialog.askdirectory()
        if save_directory:
            self.save_path_entry.delete(0, tk.END)
            self.save_path_entry.insert(0, save_directory)

    def toggle_saving(self):
        if self.is_saving:
            if self.saving_file:
                self.saving_file.close()
                self.saving_file = None
            self.is_saving = False
            self.save_button.config(text="Start Saving")
            self.browse_button.config(state=tk.NORMAL)
            self.file_name_entry.config(state=tk.NORMAL)
            if self.is_connected and not self.pause_event.is_set():
                uri = self.uri_entry.get().strip()
                self.update_status(f"Connected to {uri}", "green")
        else:
            save_path = self.save_path_entry.get()
            file_name = self.file_name_entry.get()

            if not save_path or not file_name:
                messagebox.showwarning("Saving Error", "Please select a save path and enter a file name.")
                return

            full_path = os.path.join(save_path, file_name)

            try:
                self.saving_file = open(full_path, 'a')
                self.is_saving = True
                self.save_button.config(text="Stop Saving")
                self.browse_button.config(state=tk.DISABLED)
                self.file_name_entry.config(state=tk.DISABLED)
                if self.is_connected and not self.pause_event.is_set():
                    self.update_status(f"Connected & Saving (WebSocket)", "blue")
            except Exception as e:
                messagebox.showerror("Saving Error", f"Could not open file for saving:\n{e}")
                self.is_saving = False
                if self.saving_file:
                    self.saving_file.close()
                    self.saving_file = None

    def send_data(self):
        msg = self.send_combobox.get().strip()
        if msg and (not self.command_history or self.command_history[-1] != msg):
            self.command_history.append(msg)
            if len(self.command_history) > self.max_history:
                self.command_history = self.command_history[-self.max_history:]
            self.save_command_history()
            self.update_combobox_values()

        if self.ws_app and self.is_connected:
            message = self.send_combobox.get()
            
            if self.send_json_var.get():
                try:
                    json_data = json.loads(message)
                    message = json.dumps(json_data)
                except json.JSONDecodeError:
                    try:
                        message = json.dumps({"message": message})
                    except Exception:
                        messagebox.showerror("JSON Error", "Could not format message as JSON.")
                        return

            try:
                self.ws_app.send(message)
                self.send_combobox.set("")
                timestamp = time.strftime("%H:%M:%S")
                sent_message = f"[{timestamp}] [SENT] {message}\n"
                self.process_received_message(sent_message)
            except Exception as e:
                messagebox.showerror("Send Error", f"Could not send message:\n{e}")
        else:
            messagebox.showwarning("Not Connected", "Please connect to a WebSocket server first.")

    def update_status(self, text, color):
        self.status_label.config(text=text, foreground=color)

    def apply_filter(self, event=None):
        self.filter_text = self.filter_entry.get().lower()

        if not self.filter_text:
            self.update_received_text(self.all_received_data)
        else:
            filtered_lines = [line for line in self.all_received_data.splitlines() if self.filter_text in line.lower()]
            filtered_data = "\n".join(filtered_lines)
            self.update_received_text(filtered_data)
