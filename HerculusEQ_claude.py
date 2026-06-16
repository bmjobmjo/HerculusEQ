import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import os
import json
import sys

try:
    import requests
except Exception:
    requests = None
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
import socket

from Mqtt_too import MQTTTool
from Websocket_tool import WebSocketTool

def get_application_path():
    """Get the path to the application directory (works for dev and frozen/onefile)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# App-wide settings helpers
APP_SETTINGS_FILE = os.path.join(get_application_path(), 'app_settings.json')


def load_app_settings():
    try:
        if os.path.exists(APP_SETTINGS_FILE):
            with open(APP_SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_app_settings(data: dict):
    try:
        with open(APP_SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


class SerialPortTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.serial_port = None
        self.is_connected = False
        self.reading_thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        self.saving_file = None
        self.is_saving = False

        # Added to store all received data and the filter text
        self.all_received_data = ""
        self.hex_data_buffer = ""  # Store hex binary data separately
        self.filter_text = ""

        # Line counting
        self.total_lines_received = 0
        self.last_total_lines = 0
        
        # Byte counting
        self.total_bytes_received = 0
        self.last_total_bytes = 0

        # Initialize command history before creating widgets
        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "last_commands.json")
        self.max_history = 500  # Increased to store more commands
        self.load_command_history()

        self.create_widgets()

    def create_widgets(self):
        # Frame for Serial Port Configuration
        config_frame = ttk.LabelFrame(self.frame, text="Serial Port Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")
        
        # Ensure config frame expands
        config_frame.grid_columnconfigure(1, weight=1)

        # Port Selection with Refresh Button
        ttk.Label(config_frame, text="Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")

        port_frame = ttk.Frame(config_frame)
        port_frame.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.port_combobox = ttk.Combobox(port_frame, state="readonly", width=30)
        self.port_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.refresh_button = ttk.Button(port_frame, text="⟳", width=3, command=self.list_ports)
        self.refresh_button.pack(side=tk.RIGHT, padx=3)

        self.list_ports()
        self.port_combobox.bind("<<ComboboxSelected>>", self.on_port_selected)

        # Baud Rate Selection
        ttk.Label(config_frame, text="Baud Rate:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.baud_combobox = ttk.Combobox(config_frame, values=[
            "9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"
        ], state="readonly")
        self.baud_combobox.set("115200")
        self.baud_combobox.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Data Size Selection
        ttk.Label(config_frame, text="Data Size:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.data_size_combobox = ttk.Combobox(config_frame, values=["5", "6", "7", "8"], state="readonly")
        self.data_size_combobox.set("8")
        self.data_size_combobox.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Parity Selection
        ttk.Label(config_frame, text="Parity:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.parity_combobox = ttk.Combobox(config_frame, values=["none", "even", "odd", "mark", "space"],
                                            state="readonly")
        self.parity_combobox.set("none")
        self.parity_combobox.grid(row=3, column=1, padx=5, pady=5, sticky="ew")

        # Handshake Selection
        ttk.Label(config_frame, text="Handshake:").grid(row=4, column=0, padx=5, pady=5, sticky="w")
        self.handshake_combobox = ttk.Combobox(config_frame, values=["none", "RTS/CTS", "XON/XOFF"], state="readonly")
        self.handshake_combobox.set("none")
        self.handshake_combobox.grid(row=4, column=1, padx=5, pady=5, sticky="ew")

        # Display Mode Selection
        ttk.Label(config_frame, text="Display Mode:").grid(row=5, column=0, padx=5, pady=5, sticky="w")
        self.display_mode_combobox = ttk.Combobox(config_frame, values=["Text", "Hex Binary"], state="readonly")
        self.display_mode_combobox.set("Text")
        self.display_mode_combobox.grid(row=5, column=1, padx=5, pady=5, sticky="ew")

        # Connect/Disconnect Button - Sticky EW to fill width
        self.connect_button = ttk.Button(config_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=6, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

        # Info Frame (Lines/Sec, Bytes/Sec)
        info_frame = ttk.LabelFrame(self.frame, text="Info")
        info_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        
        # Ensure Info frame expands
        info_frame.grid_columnconfigure(0, weight=1)

        # Lines/Sec Label
        self.lines_sec_label = ttk.Label(info_frame, text="Lines/Sec: -")
        self.lines_sec_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        
        # Bytes/Sec Label
        self.bytes_sec_label = ttk.Label(info_frame, text="Bytes/Sec: -")
        self.bytes_sec_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")

        # Frame for Received Data
        received_frame = ttk.LabelFrame(self.frame, text="Received Data")
        received_frame.grid(row=0, column=1, rowspan=4, padx=10, pady=10, sticky="nsew")
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        self.received_text = scrolledtext.ScrolledText(received_frame, wrap=tk.WORD, state='disabled')
        self.received_text.pack(expand=True, fill="both", padx=5, pady=5)

        # Button Frame for Pause, Clear, and Filter
        button_filter_frame = ttk.Frame(received_frame)  # New frame for buttons and filter
        button_filter_frame.pack(pady=5, fill=tk.X)  # Fill horizontally

        # Button Frame (inside button_filter_frame)
        button_frame = ttk.Frame(button_filter_frame)
        button_frame.pack(side=tk.LEFT, padx=5)

        # Pause Button
        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        # Clear Button
        self.clear_button = ttk.Button(button_frame, text="Clear", command=self.clear_received_text)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        # Filter Input (inside button_filter_frame)
        filter_input_frame = ttk.Frame(button_filter_frame)
        filter_input_frame.pack(side=tk.RIGHT, padx=5, fill=tk.X, expand=True)  # Fill horizontally
        ttk.Label(filter_input_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.filter_entry = ttk.Entry(filter_input_frame)
        self.filter_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)  # Fill horizontally
        self.filter_entry.bind("<KeyRelease>", self.apply_filter)  # Bind key release event

        # Frame for Saving Data
        save_frame = ttk.LabelFrame(self.frame, text="Save Received Data")
        save_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        # File Path Selection
        ttk.Label(save_frame, text="Save Path:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.save_path_entry = ttk.Entry(save_frame, width=30)
        self.save_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = ttk.Button(save_frame, text="Browse", command=self.browse_save_path)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5)

        # File Name
        ttk.Label(save_frame, text="File Name:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.file_name_entry = ttk.Entry(save_frame, width=30)
        self.file_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Save Button
        self.save_button = ttk.Button(save_frame, text="Start Saving", command=self.toggle_saving)
        self.save_button.grid(row=1, column=2, padx=5, pady=5)

        # Frame for Sending Data
        send_frame = ttk.LabelFrame(self.frame, text="Send Data")
        send_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        # MODIFIED: Replace simple Entry with Combobox for command history
        self.send_combobox = ttk.Combobox(send_frame, width=37)
        self.send_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data())
        # Allow typing in the combobox
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        # Update history when combobox is clicked
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.send_button = ttk.Button(send_frame, text="Send", command=self.send_data)
        self.send_button.grid(row=0, column=1, padx=5, pady=5)

        self.edit_button = ttk.Button(send_frame, text="✎", width=3, command=self.open_big_edit_box)
        self.edit_button.grid(row=0, column=2, padx=5, pady=5)

        # History button (now shows history in separate window)
        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=3, padx=5, pady=5)

        # HEX Send Checkbox
        self.send_hex_var = tk.BooleanVar()
        self.send_hex_checkbox = ttk.Checkbutton(send_frame, text="Send as HEX", variable=self.send_hex_var)
        self.send_hex_checkbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Status Label (placed below the frames)
        self.status_label = ttk.Label(self.frame, text="", anchor="w")
        self.status_label.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Update combobox with initial history
        self.update_combobox_values()
        
        # Start lines/sec update loop
        self.update_lines_per_second()

    def on_combobox_key_release(self, event):
        """Handle key release events in the combobox for better user experience."""
        # Allow normal typing behavior while maintaining dropdown functionality
        pass

    def update_combobox_values(self, event=None):
        """Update the combobox dropdown with current command history."""
        # Reverse the history so most recent commands appear at the top
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
        
        def send_from_edit():
            msg = edit_text.get('1.0', tk.END).strip()
            if msg:
                self.send_combobox.set(msg)
                self.send_data()
                edit_window.destroy()
                
        ttk.Button(button_frame, text="Send", command=send_from_edit).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=edit_window.destroy).pack(side="left")

    def show_command_history(self):
        """Show previous commands in a popup window."""
        history_window = tk.Toplevel(self.frame)
        history_window.title("Command History")
        history_window.geometry("500x300")
        history_window.transient(self.frame.winfo_toplevel())
        history_window.grab_set()

        # Create frame for better layout
        main_frame = ttk.Frame(history_window, padding="10")
        main_frame.pack(expand=True, fill="both")

        # Add label
        ttk.Label(main_frame, text="Recent Commands (most recent first):").pack(anchor="w", pady=(0, 5))

        # Buttons (pack first so they stay at the bottom)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, pady=(10, 0))

        ttk.Button(button_frame, text="Clear History", command=lambda: self.clear_command_history(history_window)).pack(
            side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=history_window.destroy).pack(side="left")

        # Create listbox widget with scrollbar
        listbox_frame = ttk.Frame(main_frame)
        listbox_frame.pack(expand=True, fill="both")

        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical")
        listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        scrollbar.config(command=listbox.yview)

        listbox.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")

        # Insert history
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
        """Clear all command history."""
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all command history?",
                                     parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Command history has been cleared.")

    def load_command_history(self):
        """Load command history from file and populate the last command."""
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
                # Set the most recent command as default
                if self.command_history:
                    # Will be set after create_widgets is called
                    pass
            except Exception as e:
                print(f"Failed to load command history: {e}")
                self.command_history = []

    def save_command_history(self):
        """Save command history to file."""
        try:
            # Keep only the most recent commands
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save command history: {e}")

    def list_ports(self):
        """Lists available serial ports with descriptions."""
        ports = list(serial.tools.list_ports.comports())
        display_names = [f"{port.device} - {port.description}" for port in ports]
        self.port_combobox['values'] = display_names
        if display_names:
            self.port_combobox.set(display_names[0])

    def on_port_selected(self, event):
        """Strip description from the selected port entry (e.g., COM11 - Bluetooth)."""
        selected = self.port_combobox.get()
        port_only = selected.split(' - ')[0]
        self.port_combobox.set(port_only)

    def toggle_connection(self):
        """Connect or disconnect from the serial port."""
        if self.is_connected:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        """Connects to the selected serial port."""
        port = self.port_combobox.get()
        baud_rate = int(self.baud_combobox.get())
        data_size = int(self.data_size_combobox.get())
        parity_str = self.parity_combobox.get()
        handshake_str = self.handshake_combobox.get()

        parity_map = {
            "none": serial.PARITY_NONE,
            "even": serial.PARITY_EVEN,
            "odd": serial.PARITY_ODD,
            "mark": serial.PARITY_MARK,
            "space": serial.PARITY_SPACE,
        }
        parity = parity_map.get(parity_str)

        rtscts = False
        xonxoff = False
        if handshake_str == "RTS/CTS":
            rtscts = True
        elif handshake_str == "XON/XOFF":
            xonxoff = True

        # If there is a lingering handle, ensure it's closed first
        try:
            if self.serial_port and getattr(self.serial_port, 'is_open', self.serial_port.isOpen()):
                self.disconnect_serial()
        except Exception:
            pass

        # Retry open a few times in case the OS hasn't released the handle yet
        last_err = None
        for attempt in range(3):
            try:
                self.serial_port = serial.Serial(
                    port=port,
                    baudrate=baud_rate,
                    bytesize=data_size,
                    parity=parity,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1,
                    rtscts=rtscts,
                    xonxoff=xonxoff,
                    dsrdtr=False  # help avoid DSR/DTR gating issues on some drivers
                )

                # Clear any stale data
                try:
                    self.serial_port.reset_input_buffer()
                    self.serial_port.reset_output_buffer()
                except Exception:
                    pass

                self.is_connected = True
                self.connect_button.config(text="Disconnect")
                self.pause_button.config(state=tk.NORMAL)
                self.update_status(f"Connected to {port}", "green")

                self.stop_event.clear()
                self.pause_event.clear()
                self.reading_thread = threading.Thread(target=self.read_from_port)
                self.reading_thread.daemon = True
                self.reading_thread.start()
                last_err = None
                break
            except serial.SerialException as e:
                last_err = e
                # Brief delay to allow Windows to release the file handle
                time.sleep(0.3)
            except Exception as e:
                last_err = e
                time.sleep(0.3)

        if last_err is not None:
            messagebox.showerror("Connection Error", f"Could not connect to port {port}:\n{last_err}")
            self.is_connected = False
            self.pause_button.config(state=tk.DISABLED)
            self.update_status("", "black")  # Clear status on error

    def disconnect_serial(self):
        """Disconnects from the serial port and ensures the handle is released."""
        if not self.serial_port:
            return

        try:
            is_open = getattr(self.serial_port, 'is_open', self.serial_port.isOpen())
        except Exception:
            is_open = False

        # Signal reader to stop first
        self.stop_event.set()
        self.pause_event.clear()

        if self.is_saving:
            try:
                self.toggle_saving()
            except Exception:
                pass

        # Give the reader thread a moment to exit
        if self.reading_thread and self.reading_thread.is_alive():
            try:
                self.reading_thread.join(timeout=2.0)
            except Exception:
                pass
        self.reading_thread = None

        # Try to gracefully drop control lines and flush buffers before closing
        try:
            if is_open:
                try:
                    self.serial_port.reset_output_buffer()
                    self.serial_port.reset_input_buffer()
                except Exception:
                    pass
                try:
                    self.serial_port.dtr = False
                    self.serial_port.rts = False
                except Exception:
                    pass
                try:
                    self.serial_port.close()
                except Exception:
                    pass
        finally:
            # Help Windows release the handle promptly
            time.sleep(0.2)
            port_name = getattr(self.serial_port, 'port', '')
            self.serial_port = None
            self.is_connected = False
            self.connect_button.config(text="Connect")
            self.pause_button.config(text="Pause", state=tk.DISABLED)
            if port_name:
                self.update_status(f"Disconnected from {port_name}", "red")
            else:
                self.update_status("Disconnected", "red")

    def toggle_pause(self):
        """Toggle pausing and resuming the reading thread."""
        if self.is_connected:
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.pause_button.config(text="Pause")
                if self.is_saving:
                    self.update_status(f"Connected & Saving ({self.serial_port.port})", "blue")
                else:
                    self.update_status(f"Connected to {self.serial_port.port}", "green")

            else:
                self.pause_event.set()
                self.pause_button.config(text="Resume")
                self.update_status(f"Paused ({self.serial_port.port})", "orange")

    def update_lines_per_second(self):
        """Updates the lines and bytes per second counter labels."""
        try:
            if self.is_connected:
                # Bytes/Sec update
                current_total_bytes = self.total_bytes_received
                bytes_diff = current_total_bytes - self.last_total_bytes
                self.last_total_bytes = current_total_bytes
                self.bytes_sec_label.config(text=f"Bytes/Sec: {bytes_diff}")

                if self.display_mode_combobox.get() == "Text":
                    current_total_lines = self.total_lines_received
                    lines_diff = current_total_lines - self.last_total_lines
                    self.last_total_lines = current_total_lines
                    self.lines_sec_label.config(text=f"Lines/Sec: {lines_diff}")
                else:
                    self.last_total_lines = self.total_lines_received
                    self.lines_sec_label.config(text="Lines/Sec: N/A (Hex)")
            else:
                # Sync last totals so we don't get a huge jump when we start/resume or switch modes
                self.last_total_lines = self.total_lines_received
                self.last_total_bytes = self.total_bytes_received
                self.lines_sec_label.config(text="Lines/Sec: -")
                self.bytes_sec_label.config(text="Bytes/Sec: -")
            
            # Schedule next update in 1 second
            self.frame.after(1000, self.update_lines_per_second)
        except Exception:
            pass

    def read_from_port(self):
        """Reads data from the serial port in a separate thread."""
        while not self.stop_event.is_set() and self.serial_port and self.serial_port.isOpen():
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue

            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    
                    # Count bytes
                    self.total_bytes_received += len(data)
                    
                    display_mode = self.display_mode_combobox.get()

                    if display_mode == "Hex Binary":
                        # Convert binary data to hex format with spaces
                        hex_data = ' '.join(f'{byte:02x}' for byte in data)
                        hex_line = hex_data + '\n'
                        self.hex_data_buffer += hex_line

                        # Save hex data if saving is enabled
                        if self.is_saving and self.saving_file:
                            try:
                                self.saving_file.write(hex_line)
                                self.saving_file.flush()
                            except Exception as e:
                                print(f"Error writing to save file: {e}")
                                self.notebook.winfo_toplevel().after(0, self.toggle_saving)
                                self.notebook.winfo_toplevel().after(0, lambda: messagebox.showerror("Saving Error",
                                                                                                     f"Error writing to file:\n{e}\nSaving stopped."))

                        self.notebook.winfo_toplevel().after(0, self.update_hex_display)
                    else:
                        # Text mode - original behavior
                        try:
                            decoded_data = data.decode('utf-8', errors='replace')
                        except UnicodeDecodeError:
                            decoded_data = data.decode('latin-1', errors='replace')

                        # Count lines
                        self.total_lines_received += decoded_data.count('\n')

                        # Append new data to the full received data storage
                        self.all_received_data += decoded_data
                        # Process data with the current filter
                        self.notebook.winfo_toplevel().after(0, self.process_received_data, decoded_data)

                time.sleep(0.01)
            except serial.SerialException as e:
                print(f"Error reading from serial port: {e}")
                self.notebook.winfo_toplevel().after(0, self.disconnect_serial)
                break
            except Exception as e:
                print(f"An unexpected error occurred during reading: {e}")
                self.notebook.winfo_toplevel().after(0, self.disconnect_serial)
                break

    def process_received_data(self, data):
        """Updates the received data text area based on the filter and saves data if saving is active."""
        self.apply_filter()  # Re-apply filter to include the newly received data

        if self.is_saving and self.saving_file:
            try:
                self.saving_file.write(data)
                self.saving_file.flush()
            except Exception as e:
                print(f"Error writing to save file: {e}")
                self.toggle_saving()
                messagebox.showerror("Saving Error", f"Error writing to file:\n{e}\nSaving stopped.")

    def update_received_text(self, data):
        """Updates the received data text area."""
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)  # Clear current content
        self.received_text.insert(tk.END, data)
        self.received_text.see(tk.END)
        # self.received_text.config(state='disabled')

    def update_hex_display(self):
        """Updates the hex display with continuous streaming data."""
        self.received_text.config(state='normal')
        self.received_text.insert(tk.END, self.hex_data_buffer)
        self.received_text.see(tk.END)
        self.hex_data_buffer = ""  # Clear buffer after display

    def clear_received_text(self):
        """Clears the received data text area and the stored data."""
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.config(state='disabled')
        self.all_received_data = ""  # Also clear the stored data
        self.hex_data_buffer = ""  # Clear hex data buffer
        self.filter_entry.delete(0, tk.END)  # Clear the filter entry
        self.filter_text = ""  # Reset filter text

    def browse_save_path(self):
        """Opens a file dialog to select a save path."""
        save_directory = filedialog.askdirectory()
        if save_directory:
            self.save_path_entry.delete(0, tk.END)
            self.save_path_entry.insert(0, save_directory)

    def toggle_saving(self):
        """Starts or stops saving the received data to a file."""
        if self.is_saving:
            if self.saving_file:
                self.saving_file.close()
                self.saving_file = None
            self.is_saving = False
            self.save_button.config(text="Start Saving")
            self.browse_button.config(state=tk.NORMAL)
            self.file_name_entry.config(state=tk.NORMAL)
            if self.is_connected and not self.pause_event.is_set():
                self.update_status(f"Connected to {self.serial_port.port}", "green")
            elif hasattr(self, 'status_label'):
                pass

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
                    self.update_status(f"Connected & Saving ({self.serial_port.port})", "blue")


            except Exception as e:
                messagebox.showerror("Saving Error", f"Could not open file for saving:\n{e}")
                self.is_saving = False
                if self.saving_file:
                    self.saving_file.close()
                    self.saving_file = None

    def send_data(self):
        """Sends data from the input field to the serial port."""
        cmd = self.send_combobox.get().strip()

        # Add command to history if it's not empty and not already the most recent
        if cmd and (not self.command_history or self.command_history[-1] != cmd):
            self.command_history.append(cmd)
            # Keep only the most recent commands
            if len(self.command_history) > self.max_history:
                self.command_history = self.command_history[-self.max_history:]
            self.save_command_history()
            self.update_combobox_values()

        if self.serial_port and self.serial_port.isOpen():
            data_to_send_str = self.send_combobox.get()
            data_to_send_bytes = b''

            if self.send_hex_var.get():
                try:
                    hex_bytes = bytes.fromhex(data_to_send_str.replace(" ", ""))
                    data_to_send_bytes = hex_bytes
                except ValueError:
                    messagebox.showerror("Send Error",
                                         "Invalid HEX string entered. Please use space-separated hex values (e.g., FF 55 AA).")
                    return
            else:
                data_to_send_str_with_newline = data_to_send_str + '\r\n'
                data_to_send_bytes = data_to_send_str_with_newline.encode('utf-8')

            try:
                self.serial_port.write(data_to_send_bytes)
                # Clear the combobox after successful send
                self.send_combobox.set("")
            except serial.SerialException as e:
                messagebox.showerror("Send Error", f"Could not send data:\n{e}")
            except Exception as e:
                messagebox.showerror("Send Error", f"An unexpected error occurred during sending: {e}")
        else:
            messagebox.showwarning("Not Connected", "Please connect to a serial port first.")

    def update_status(self, text, color):
        """Updates the status label."""
        self.status_label.config(text=text, foreground=color)

    def apply_filter(self, event=None):
        """Applies the filter to the received data and updates the text box."""
        self.filter_text = self.filter_entry.get().lower()  # Get filter text and convert to lowercase

        if not self.filter_text:
            # If filter is empty, display all data
            self.update_received_text(self.all_received_data)
        else:
            # Filter lines containing the filter text
            filtered_lines = [line for line in self.all_received_data.splitlines() if self.filter_text in line.lower()]
            filtered_data = "\n".join(filtered_lines)
            self.update_received_text(filtered_data)


class TCPClientTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.socket = None
        self.is_connected = False
        self.reading_thread = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

        self.saving_file = None
        self.is_saving = False

        # Store all received data and filter text
        self.all_received_data = ""
        self.filter_text = ""

        # Connection type (TCP or UDP)
        self.connection_type = "TCP"

        # Initialize command history before creating widgets
        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "tcp_commands.json")
        self.max_history = 500
        self.load_command_history()

        self.create_widgets()

    def create_widgets(self):
        # Frame for TCP/UDP Client Configuration
        config_frame = ttk.LabelFrame(self.frame, text="Connection Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        # Connection Type Selection
        ttk.Label(config_frame, text="Protocol:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.protocol_combobox = ttk.Combobox(config_frame, values=["TCP", "UDP"], state="readonly")
        self.protocol_combobox.set("TCP")
        self.protocol_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.protocol_combobox.bind("<<ComboboxSelected>>", self.on_protocol_changed)

        # Server IP Address
        ttk.Label(config_frame, text="Server IP:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.ip_entry = ttk.Entry(config_frame, width=20)
        self.ip_entry.insert(0, "127.0.0.1")  # Default localhost
        self.ip_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Server Port
        ttk.Label(config_frame, text="Port:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.port_entry = ttk.Entry(config_frame, width=20)
        self.port_entry.insert(0, "8080")  # Default port
        self.port_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Timeout setting
        ttk.Label(config_frame, text="Timeout (s):").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.timeout_entry = ttk.Entry(config_frame, width=20)
        self.timeout_entry.insert(0, "5")  # Default 5 seconds
        self.timeout_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")

        # Connect/Disconnect Button
        self.connect_button = ttk.Button(config_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=4, column=0, columnspan=2, padx=5, pady=10)

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

        # Button Frame
        button_frame = ttk.Frame(button_filter_frame)
        button_frame.pack(side=tk.LEFT, padx=5)

        # Pause Button
        self.pause_button = ttk.Button(button_frame, text="Pause", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        # Clear Button
        self.clear_button = ttk.Button(button_frame, text="Clear", command=self.clear_received_text)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        # Filter Input
        filter_input_frame = ttk.Frame(button_filter_frame)
        filter_input_frame.pack(side=tk.RIGHT, padx=5, fill=tk.X, expand=True)
        ttk.Label(filter_input_frame, text="Filter:").pack(side=tk.LEFT, padx=5)
        self.filter_entry = ttk.Entry(filter_input_frame)
        self.filter_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.filter_entry.bind("<KeyRelease>", self.apply_filter)

        # Frame for Saving Data
        save_frame = ttk.LabelFrame(self.frame, text="Save Received Data")
        save_frame.grid(row=2, column=0, padx=10, pady=10, sticky="sw")

        # File Path Selection
        ttk.Label(save_frame, text="Save Path:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.save_path_entry = ttk.Entry(save_frame, width=30)
        self.save_path_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.browse_button = ttk.Button(save_frame, text="Browse", command=self.browse_save_path)
        self.browse_button.grid(row=0, column=2, padx=5, pady=5)

        # File Name
        ttk.Label(save_frame, text="File Name:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.file_name_entry = ttk.Entry(save_frame, width=30)
        self.file_name_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Save Button
        self.save_button = ttk.Button(save_frame, text="Start Saving", command=self.toggle_saving)
        self.save_button.grid(row=1, column=2, padx=5, pady=5)

        # Frame for Sending Data
        send_frame = ttk.LabelFrame(self.frame, text="Send Data")
        send_frame.grid(row=1, column=0, padx=10, pady=10, sticky="sw")

        # Command input with history
        self.send_combobox = ttk.Combobox(send_frame, width=37)
        self.send_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data())
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.send_button = ttk.Button(send_frame, text="Send", command=self.send_data)
        self.send_button.grid(row=0, column=1, padx=5, pady=5)

        self.edit_button = ttk.Button(send_frame, text="✎", width=3, command=self.open_big_edit_box)
        self.edit_button.grid(row=0, column=2, padx=5, pady=5)

        # History button
        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=3, padx=5, pady=5)

        # HEX Send Checkbox
        self.send_hex_var = tk.BooleanVar()
        self.send_hex_checkbox = ttk.Checkbutton(send_frame, text="Send as HEX", variable=self.send_hex_var)
        self.send_hex_checkbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Status Label
        self.status_label = ttk.Label(self.frame, text="", anchor="w")
        self.status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Update combobox with initial history
        self.update_combobox_values()

    def on_protocol_changed(self, event):
        """Handle protocol selection change."""
        self.connection_type = self.protocol_combobox.get()
        if self.is_connected:
            self.disconnect_client()

    def on_combobox_key_release(self, event):
        """Handle key release events in the combobox."""
        pass

    def update_combobox_values(self, event=None):
        """Update the combobox dropdown with current command history."""
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
        
        def send_from_edit():
            msg = edit_text.get('1.0', tk.END).strip()
            if msg:
                self.send_combobox.set(msg)
                self.send_data()
                edit_window.destroy()
                
        ttk.Button(button_frame, text="Send", command=send_from_edit).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=edit_window.destroy).pack(side="left")

    def show_command_history(self):
        """Show previous commands in a popup window."""
        history_window = tk.Toplevel(self.frame)
        history_window.title("Command History")
        history_window.geometry("500x300")
        history_window.transient(self.frame.winfo_toplevel())
        history_window.grab_set()

        main_frame = ttk.Frame(history_window, padding="10")
        main_frame.pack(expand=True, fill="both")

        ttk.Label(main_frame, text="Recent Commands (most recent first):").pack(anchor="w", pady=(0, 5))

        # Buttons (pack first so they stay at the bottom)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, pady=(10, 0))

        ttk.Button(button_frame, text="Clear History", command=lambda: self.clear_command_history(history_window)).pack(
            side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=history_window.destroy).pack(side="left")

        # Create listbox widget with scrollbar
        listbox_frame = ttk.Frame(main_frame)
        listbox_frame.pack(expand=True, fill="both")

        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical")
        listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=("Consolas", 10))
        scrollbar.config(command=listbox.yview)

        listbox.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")

        # Insert history
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
        """Clear all command history."""
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all command history?",
                                     parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Command history has been cleared.")

    def load_command_history(self):
        """Load command history from file."""
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
            except Exception as e:
                print(f"Failed to load command history: {e}")
                self.command_history = []

    def save_command_history(self):
        """Save command history to file."""
        try:
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save command history: {e}")

    def toggle_connection(self):
        """Connect or disconnect from the server."""
        if self.is_connected:
            self.disconnect_client()
        else:
            self.connect_client()

    def connect_client(self):
        """Connect to the server."""
        try:
            server_ip = self.ip_entry.get().strip()
            server_port = int(self.port_entry.get().strip())
            timeout = float(self.timeout_entry.get().strip())

            if not server_ip or not server_port:
                messagebox.showwarning("Connection Error", "Please enter server IP and port.")
                return

            import socket

            if self.connection_type == "TCP":
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(timeout)
                self.socket.connect((server_ip, server_port))
            else:  # UDP
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.settimeout(0.1)  # Short timeout for UDP
                self.server_address = (server_ip, server_port)

            self.is_connected = True
            self.connect_button.config(text="Disconnect")
            self.pause_button.config(state=tk.NORMAL)
            self.update_status(f"Connected to {server_ip}:{server_port} ({self.connection_type})", "green")

            # Disable connection settings while connected
            self.protocol_combobox.config(state="disabled")
            self.ip_entry.config(state="disabled")
            self.port_entry.config(state="disabled")
            self.timeout_entry.config(state="disabled")

            self.stop_event.clear()
            self.pause_event.clear()
            self.reading_thread = threading.Thread(target=self.read_from_socket)
            self.reading_thread.daemon = True
            self.reading_thread.start()

        except ValueError:
            messagebox.showerror("Connection Error", "Invalid port number or timeout value.")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to {server_ip}:{server_port}:\n{e}")
            self.is_connected = False
            self.pause_button.config(state=tk.DISABLED)
            self.update_status("", "black")

    def disconnect_client(self):
        """Disconnect from the server."""
        if self.socket:
            self.stop_event.set()
            self.pause_event.clear()
            if self.is_saving:
                self.toggle_saving()

            if self.reading_thread and self.reading_thread.is_alive():
                self.reading_thread.join(timeout=1.0)

            try:
                self.socket.close()
            except:
                pass

            self.socket = None
            self.is_connected = False
            self.connect_button.config(text="Connect")
            self.pause_button.config(text="Pause", state=tk.DISABLED)

            # Re-enable connection settings
            self.protocol_combobox.config(state="readonly")
            self.ip_entry.config(state="normal")
            self.port_entry.config(state="normal")
            self.timeout_entry.config(state="normal")

            self.update_status("Disconnected", "red")

    def toggle_pause(self):
        """Toggle pausing and resuming the reading thread."""
        if self.is_connected:
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.pause_button.config(text="Pause")
                if self.is_saving:
                    self.update_status(f"Connected & Saving ({self.connection_type})", "blue")
                else:
                    server_info = f"{self.ip_entry.get()}:{self.port_entry.get()}"
                    self.update_status(f"Connected to {server_info} ({self.connection_type})", "green")
            else:
                self.pause_event.set()
                self.pause_button.config(text="Resume")
                self.update_status(f"Paused ({self.connection_type})", "orange")

    def read_from_socket(self):
        """Read data from the socket in a separate thread."""
        import socket

        while not self.stop_event.is_set() and self.socket:
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue

            try:
                if self.connection_type == "TCP":
                    data = self.socket.recv(4096)
                    if not data:  # Connection closed by server
                        self.notebook.winfo_toplevel().after(0, self.disconnect_client)
                        break
                else:  # UDP
                    try:
                        data, addr = self.socket.recvfrom(4096)
                    except socket.timeout:
                        continue

                try:
                    decoded_data = data.decode('utf-8', errors='replace')
                except UnicodeDecodeError:
                    decoded_data = data.decode('latin-1', errors='replace')

                # Add timestamp for network data
                timestamp = time.strftime("%H:%M:%S")
                timestamped_data = f"[{timestamp}] {decoded_data}"

                self.all_received_data += timestamped_data
                self.notebook.winfo_toplevel().after(0, self.process_received_data, timestamped_data)

                time.sleep(0.01)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Error reading from socket: {e}")
                self.notebook.winfo_toplevel().after(0, self.disconnect_client)
                break

    def process_received_data(self, data):
        """Process received data and update display."""
        self.apply_filter()

        if self.is_saving and self.saving_file:
            try:
                self.saving_file.write(data)
                self.saving_file.flush()
            except Exception as e:
                print(f"Error writing to save file: {e}")
                self.toggle_saving()
                messagebox.showerror("Saving Error", f"Error writing to file:\n{e}\nSaving stopped.")

    def update_received_text(self, data):
        """Update the received data text area."""
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.insert(tk.END, data)
        self.received_text.see(tk.END)

    def clear_received_text(self):
        """Clear the received data text area and stored data."""
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.config(state='disabled')
        self.all_received_data = ""
        self.filter_entry.delete(0, tk.END)
        self.filter_text = ""

    def browse_save_path(self):
        """Open file dialog to select save path."""
        save_directory = filedialog.askdirectory()
        if save_directory:
            self.save_path_entry.delete(0, tk.END)
            self.save_path_entry.insert(0, save_directory)

    def toggle_saving(self):
        """Start or stop saving received data to file."""
        if self.is_saving:
            if self.saving_file:
                self.saving_file.close()
                self.saving_file = None
            self.is_saving = False
            self.save_button.config(text="Start Saving")
            self.browse_button.config(state=tk.NORMAL)
            self.file_name_entry.config(state=tk.NORMAL)
            if self.is_connected and not self.pause_event.is_set():
                server_info = f"{self.ip_entry.get()}:{self.port_entry.get()}"
                self.update_status(f"Connected to {server_info} ({self.connection_type})", "green")
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
                    self.update_status(f"Connected & Saving ({self.connection_type})", "blue")
            except Exception as e:
                messagebox.showerror("Saving Error", f"Could not open file for saving:\n{e}")
                self.is_saving = False
                if self.saving_file:
                    self.saving_file.close()
                    self.saving_file = None

    def send_data(self):
        """Send data to the server."""
        cmd = self.send_combobox.get().strip()

        # Add command to history
        if cmd and (not self.command_history or self.command_history[-1] != cmd):
            self.command_history.append(cmd)
            if len(self.command_history) > self.max_history:
                self.command_history = self.command_history[-self.max_history:]
            self.save_command_history()
            self.update_combobox_values()

        if self.socket:
            import socket
            data_to_send_str = self.send_combobox.get()
            data_to_send_bytes = b''

            if self.send_hex_var.get():
                try:
                    hex_bytes = bytes.fromhex(data_to_send_str.replace(" ", ""))
                    data_to_send_bytes = hex_bytes
                except ValueError:
                    messagebox.showerror("Send Error",
                                         "Invalid HEX string entered. Please use space-separated hex values (e.g., FF 55 AA).")
                    return
            else:
                data_to_send_str_with_newline = data_to_send_str + '\n'
                data_to_send_bytes = data_to_send_str_with_newline.encode('utf-8')

            try:
                if self.connection_type == "TCP":
                    self.socket.send(data_to_send_bytes)
                else:  # UDP
                    self.socket.sendto(data_to_send_bytes, self.server_address)

                # Clear the combobox after successful send
                self.send_combobox.set("")
            except Exception as e:
                messagebox.showerror("Send Error", f"Could not send data:\n{e}")
        else:
            messagebox.showwarning("Not Connected", "Please connect to a server first.")

    def update_status(self, text, color):
        """Update the status label."""
        self.status_label.config(text=text, foreground=color)

    def apply_filter(self, event=None):
        """Apply filter to received data and update text box."""
        self.filter_text = self.filter_entry.get().lower()

        if not self.filter_text:
            self.update_received_text(self.all_received_data)
        else:
            filtered_lines = [line for line in self.all_received_data.splitlines() if self.filter_text in line.lower()]
            filtered_data = "\n".join(filtered_lines)
            self.update_received_text(filtered_data)


class TCPServerTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.server_socket = None
        self.is_running = False
        self.clients = {}  # Dictionary to store client sockets and their addresses
        self.client_threads = {}  # Dictionary to store client threads
        self.server_thread = None
        self.stop_event = threading.Event()

        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "tcpserver_commands.json")
        self.max_history = 500
        self.load_command_history()

        self.create_widgets()

    def create_widgets(self):
        # Top frame for server controls
        top_frame = ttk.Frame(self.frame)
        top_frame.pack(fill=tk.X, pady=5)

        ttk.Label(top_frame, text="Port:").pack(side=tk.LEFT, padx=5)
        self.port_entry = ttk.Entry(top_frame, width=10)
        self.port_entry.insert(0, "8080")
        self.port_entry.pack(side=tk.LEFT, padx=5)

        self.start_button = ttk.Button(top_frame, text="Start", command=self.start_server)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(top_frame, text="Stop", command=self.stop_server, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # Status box
        status_frame = ttk.LabelFrame(self.frame, text="Status")
        status_frame.pack(expand=True, fill="both", padx=10, pady=10)

        self.status_box = scrolledtext.ScrolledText(status_frame, wrap=tk.WORD, state='disabled')
        self.status_box.pack(expand=True, fill="both")

        # Send data frame
        send_frame = ttk.LabelFrame(self.frame, text="Send Data")
        send_frame.pack(fill=tk.X, padx=10, pady=5)

        self.send_combobox = ttk.Combobox(send_frame, width=50)
        self.send_combobox.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5, pady=5)
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data_to_client())
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.client_selector = ttk.Combobox(send_frame, state="readonly")
        self.client_selector.pack(side=tk.LEFT, padx=5)
        self.client_selector.set("No clients connected")

        self.send_button = ttk.Button(send_frame, text="Send", command=self.send_data_to_client)
        self.send_button.pack(side=tk.LEFT, padx=5)

        self.edit_button = ttk.Button(send_frame, text="✎", width=3, command=self.open_big_edit_box)
        self.edit_button.pack(side=tk.LEFT, padx=5)

        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.pack(side=tk.LEFT, padx=5)

        self.update_combobox_values()

    def update_status(self, message):
        self.status_box.config(state='normal')
        self.status_box.insert(tk.END, message + "\n")
        self.status_box.see(tk.END)
        self.status_box.config(state='disabled')

    def start_server(self):
        port_str = self.port_entry.get()
        if not port_str.isdigit():
            messagebox.showerror("Error", "Invalid port number.")
            return
        port = int(port_str)

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.server_socket.bind(("", port))
            self.server_socket.listen(5)
            self.is_running = True
            self.stop_event.clear()
            self.server_thread = threading.Thread(target=self.accept_connections)
            self.server_thread.daemon = True
            self.server_thread.start()

            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.port_entry.config(state=tk.DISABLED)
            self.update_status(f"Server started on port {port}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start server: {e}")
            self.server_socket.close()
            self.server_socket = None

    def stop_server(self):
        if self.is_running:
            self.stop_event.set()
            for client_socket in self.clients.values():
                client_socket.close()
            self.clients.clear()
            self.client_threads.clear()

            # To unblock the accept() call
            try:
                # Create a dummy connection to unblock the accept call
                dummy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dummy_socket.connect(("127.0.0.1", int(self.port_entry.get())))
                dummy_socket.close()
            except Exception as e:
                print(f"Error closing server socket: {e}")

            self.server_socket.close()
            self.is_running = False
            self.server_socket = None

            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.port_entry.config(state=tk.NORMAL)
            self.update_status("Server stopped")
            self.update_client_selector()

    def accept_connections(self):
        while not self.stop_event.is_set():
            try:
                client_socket, addr = self.server_socket.accept()
                if self.stop_event.is_set():
                    client_socket.close()
                    break

                client_addr_str = f"{addr[0]}:{addr[1]}"
                self.clients[client_addr_str] = client_socket
                self.update_status(f"Accepted connection from {client_addr_str}")
                self.update_client_selector()

                thread = threading.Thread(target=self.handle_client, args=(client_socket, client_addr_str))
                thread.daemon = True
                thread.start()
                self.client_threads[client_addr_str] = thread
            except Exception as e:
                if not self.stop_event.is_set():
                    self.update_status(f"Error accepting connections: {e}")
                break

    def handle_client(self, client_socket, addr):
        while not self.stop_event.is_set():
            try:
                data = client_socket.recv(1024)
                if not data:
                    break
                self.update_status(f"[{addr}] Received: {data.decode('utf-8', 'ignore')}")
            except Exception as e:
                break

        client_socket.close()
        if addr in self.clients:
            del self.clients[addr]
        self.update_status(f"Connection from {addr} closed.")
        self.update_client_selector()

    def send_data_to_client(self):
        selected_client = self.client_selector.get()
        if selected_client == "No clients connected" or not selected_client:
            messagebox.showwarning("Warning", "No client selected.")
            return

        data_to_send = self.send_combobox.get()
        if not data_to_send:
            messagebox.showwarning("Warning", "No data to send.")
            return

        if not self.command_history or self.command_history[-1] != data_to_send:
            self.command_history.append(data_to_send)
            if len(self.command_history) > self.max_history:
                self.command_history = self.command_history[-self.max_history:]
            self.save_command_history()
            self.update_combobox_values()

        client_socket = self.clients.get(selected_client)
        if client_socket:
            try:
                client_socket.sendall((data_to_send + '\r\n').encode('utf-8'))
                self.update_status(f"Sent to {selected_client}: {data_to_send}")
            except Exception as e:
                self.update_status(f"Error sending to {selected_client}: {e}")
        else:
            messagebox.showerror("Error", "Selected client is no longer connected.")

    def update_client_selector(self):
        client_addrs = list(self.clients.keys())
        if client_addrs:
            self.client_selector['values'] = client_addrs
            self.client_selector.set(client_addrs[0])
        else:
            self.client_selector['values'] = []
            self.client_selector.set("No clients connected")

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
        
        def send_from_edit():
            msg = edit_text.get('1.0', tk.END).strip()
            if msg:
                self.send_combobox.set(msg)
                self.send_data_to_client()
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

        ttk.Label(main_frame, text="Recent Commands (most recent first):").pack(anchor="w", pady=(0, 5))

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
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all command history?", parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Command history has been cleared.")

    def load_command_history(self):
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
            except Exception as e:
                print(f"Failed to load command history: {e}")
                self.command_history = []

    def save_command_history(self):
        try:
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save command history: {e}")


class UDPTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.socket = None
        self.is_running = False
        self.receive_thread = None
        self.stop_event = threading.Event()

        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "udp_commands.json")
        self.max_history = 500
        self.load_command_history()

        # Config variables
        self.mode_var = tk.StringVar(value="Both")
        self.local_port_var = tk.StringVar(value="8082")
        self.remote_ip_var = tk.StringVar(value="127.0.0.1")
        self.remote_port_var = tk.StringVar(value="8083")
        self.broadcast_var = tk.BooleanVar(value=False)
        self.last_ip = "127.0.0.1"

        self.create_widgets()

    def create_widgets(self):
        # Configuration Frame
        config_frame = ttk.LabelFrame(self.frame, text="UDP Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        # Mode Selection
        ttk.Label(config_frame, text="Mode:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.mode_combobox = ttk.Combobox(config_frame, textvariable=self.mode_var,
                                          values=["Inbound", "Outbound", "Both"], state="readonly")
        self.mode_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.mode_combobox.bind("<<ComboboxSelected>>", self.on_mode_changed)

        # Local Port (for Inbound/Both)
        self.local_port_label = ttk.Label(config_frame, text="Local Port:")
        self.local_port_entry = ttk.Entry(config_frame, textvariable=self.local_port_var, width=10)

        # Remote IP/Port (for Outbound/Both)
        self.remote_ip_label = ttk.Label(config_frame, text="Remote IP:")
        self.remote_ip_entry = ttk.Entry(config_frame, textvariable=self.remote_ip_var, width=15)
        self.remote_port_label = ttk.Label(config_frame, text="Remote Port:")
        self.remote_port_entry = ttk.Entry(config_frame, textvariable=self.remote_port_var, width=10)

        # Broadcast Checkbox
        self.broadcast_check = ttk.Checkbutton(config_frame, text="Broadcast", variable=self.broadcast_var,
                                               command=self.on_broadcast_changed)

        # Start/Stop Button
        self.action_button = ttk.Button(config_frame, text="Start", command=self.toggle_connection)
        self.action_button.grid(row=5, column=0, columnspan=2, padx=5, pady=10)

        # Received Data Area
        received_frame = ttk.LabelFrame(self.frame, text="Received Data")
        received_frame.grid(row=0, column=1, rowspan=3, padx=10, pady=10, sticky="nsew")
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        self.received_text = scrolledtext.ScrolledText(received_frame, wrap=tk.WORD, state='disabled')
        self.received_text.pack(expand=True, fill="both", padx=5, pady=5)

        # Clear Button
        ttk.Button(received_frame, text="Clear", command=self.clear_received).pack(anchor="e", padx=5, pady=5)

        # Send Data Area
        self.send_frame = ttk.LabelFrame(self.frame, text="Send Data")
        self.send_frame.grid(row=1, column=0, padx=10, pady=10, sticky="sw")

        self.send_combobox = ttk.Combobox(self.send_frame, width=30)
        self.send_combobox.pack(side=tk.LEFT, padx=5, pady=5, expand=True, fill=tk.X)
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data())
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.send_button = ttk.Button(self.send_frame, text="Send", command=self.send_data)
        self.send_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.edit_button = ttk.Button(self.send_frame, text="✎", width=3, command=self.open_big_edit_box)
        self.edit_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.history_button = ttk.Button(self.send_frame, text="History", command=self.show_command_history)
        self.history_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        self.update_combobox_values()

        self.status_label = ttk.Label(self.frame, text="Status: Stopped", foreground="red")
        self.status_label.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        # Initial Layout update
        self.on_mode_changed()

    def on_mode_changed(self, event=None):
        mode = self.mode_var.get()

        # Clear grid for dynamic widgets
        self.local_port_label.grid_remove()
        self.local_port_entry.grid_remove()
        self.remote_ip_label.grid_remove()
        self.remote_ip_entry.grid_remove()
        self.remote_port_label.grid_remove()
        self.remote_port_entry.grid_remove()
        self.broadcast_check.grid_remove()
        self.send_frame.grid_remove()

        row_idx = 1
        if mode in ["Inbound", "Both"]:
            self.local_port_label.grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
            self.local_port_entry.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
            row_idx += 1

        if mode in ["Outbound", "Both"]:
            self.remote_ip_label.grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
            self.remote_ip_entry.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
            row_idx += 1
            self.remote_port_label.grid(row=row_idx, column=0, padx=5, pady=5, sticky="w")
            self.remote_port_entry.grid(row=row_idx, column=1, padx=5, pady=5, sticky="ew")
            row_idx += 1
            self.broadcast_check.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=5, sticky="w")
            row_idx += 1
            # Show send frame
            self.send_frame.grid()

        # Adjust button row
        self.action_button.grid(row=row_idx, column=0, columnspan=2, padx=5, pady=10)

    def on_broadcast_changed(self):
        if self.broadcast_var.get():
            self.last_ip = self.remote_ip_var.get()
            self.remote_ip_var.set("255.255.255.255")
            self.remote_ip_entry.config(state="disabled")
        else:
            self.remote_ip_var.set(self.last_ip)
            self.remote_ip_entry.config(state="normal")

    def toggle_connection(self):
        if self.is_running:
            self.stop_udp()
        else:
            self.start_udp()

    def start_udp(self):
        mode = self.mode_var.get()
        local_port_str = self.local_port_var.get()
        
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Enable Broadcast
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            if mode in ["Inbound", "Both"]:
                if not local_port_str.isdigit():
                     messagebox.showerror("Error", "Invalid Local Port")
                     return
                local_port = int(local_port_str)
                self.socket.bind(("", local_port))
                self.update_status(f"Bound to UDP port {local_port}", "green")
            else:
                self.update_status("Ready to send (Outbound)", "green")

            self.is_running = True
            self.stop_event.clear()
            self.action_button.config(text="Stop")

            # Disable config inputs
            self.mode_combobox.config(state="disabled")
            self.local_port_entry.config(state="disabled")
            if not self.broadcast_var.get():
                self.remote_ip_entry.config(state="disabled")
            self.remote_port_entry.config(state="disabled")
            self.broadcast_check.config(state="disabled")

            # Start listener thread
            self.receive_thread = threading.Thread(target=self.receive_loop)
            self.receive_thread.daemon = True
            self.receive_thread.start()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to start UDP: {e}")
            self.stop_udp()

    def stop_udp(self):
        self.is_running = False
        self.stop_event.set()
        if self.socket:
            self.socket.close()
            self.socket = None

        self.action_button.config(text="Start")
        self.mode_combobox.config(state="readonly")
        self.local_port_entry.config(state="normal")
        if self.broadcast_var.get():
             self.remote_ip_entry.config(state="disabled")
        else:
             self.remote_ip_entry.config(state="normal")
        self.remote_port_entry.config(state="normal")
        self.broadcast_check.config(state="normal")
        self.update_status("Stopped", "red")

    def receive_loop(self):
        while self.is_running and self.socket:
            try:
                # Use select or timeout to allow checking stop_event
                self.socket.settimeout(1.0)
                try:
                    data, addr = self.socket.recvfrom(4096)
                    timestamp = time.strftime("%H:%M:%S")
                    msg = f"[{timestamp}] [{addr[0]}:{addr[1]}] {data.decode('utf-8', errors='replace')}\n"
                    self.notebook.winfo_toplevel().after(0, self.append_received, msg)
                except socket.timeout:
                    continue
                except OSError:
                    break
            except Exception as e:
                print(f"UDP Receive Error: {e}")
                break

    def append_received(self, msg):
        self.received_text.config(state='normal')
        self.received_text.insert(tk.END, msg)
        self.received_text.see(tk.END)
        self.received_text.config(state='disabled')

    def clear_received(self):
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.config(state='disabled')

    def send_data(self):
        if not self.socket:
            return

        mode = self.mode_var.get()
        if mode == "Inbound":
            messagebox.showwarning("Warning", "Cannot send in Inbound mode.")
            return

        try:
            target_ip = self.remote_ip_var.get()
            target_port_str = self.remote_port_var.get()
            
            if not target_ip or not target_port_str.isdigit():
                 messagebox.showerror("Error", "Invalid Remote IP or Port")
                 return
            
            target_port = int(target_port_str)
            data = self.send_combobox.get()

            if not data:
                return

            if not self.command_history or self.command_history[-1] != data:
                self.command_history.append(data)
                if len(self.command_history) > self.max_history:
                    self.command_history = self.command_history[-self.max_history:]
                self.save_command_history()
                self.update_combobox_values()

            self.socket.sendto(data.encode('utf-8'), (target_ip, target_port))
            timestamp = time.strftime("%H:%M:%S")
            self.append_received(f"[{timestamp}] [You -> {target_ip}:{target_port}] {data}\n")
            self.send_combobox.set("")
        except Exception as e:
            messagebox.showerror("Send Error", f"Failed to send: {e}")

    def update_status(self, text, color):
        self.status_label.config(text=f"Status: {text}", foreground=color)

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
        
        def send_from_edit():
            msg = edit_text.get('1.0', tk.END).strip()
            if msg:
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

        ttk.Label(main_frame, text="Recent Commands (most recent first):").pack(anchor="w", pady=(0, 5))

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
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all command history?", parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Command history has been cleared.")

    def load_command_history(self):
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
            except Exception as e:
                print(f"Failed to load command history: {e}")
                self.command_history = []

    def save_command_history(self):
        try:
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save command history: {e}")


class AboutTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="20")
        self.frame.pack(expand=True, fill="both")
        
        self.create_widgets()
        
    def create_widgets(self):
        title_label = ttk.Label(self.frame, text="HerculusEQ", font=("Helvetica", 24, "bold"))
        title_label.pack(pady=(20, 10))
        
        version_label = ttk.Label(self.frame, text="Version 1.0.20260616", font=("Helvetica", 14))
        version_label.pack(pady=(0, 20))
        
        desc_label = ttk.Label(self.frame, text="A comprehensive, multi-protocol desktop testing utility.\n"
                                                "Designed for developers, hardware engineers, and IoT integrators.\n\n"
                                                "Features:\n"
                                                "- Serial Port Terminal\n"
                                                "- TCP Client & Server\n"
                                                "- UDP Terminal\n"
                                                "- MQTT Client\n"
                                                "- WebSocket Client\n"
                                                "- REST Client\n",
                               justify=tk.CENTER, font=("Helvetica", 12))
        desc_label.pack(pady=10)


class MainApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("Communication Tool")
        self.root.geometry("1000x700")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, expand=True, fill="both")

        # Create and add Serial tab
        self.serial_tool = SerialPortTool(self.notebook)
        self.notebook.add(self.serial_tool.frame, text='Serial')  # Add the frame from the instance

        # Create and add TCP Client tab
        self.tcp_client_tool = TCPClientTool(self.notebook)
        self.notebook.add(self.tcp_client_tool.frame, text='TCP Client')  # Add the frame from the instance

        # Create and add TCP Server tab
        self.tcp_server_tool = TCPServerTool(self.notebook)
        self.notebook.add(self.tcp_server_tool.frame, text='TCP Server')  # Add the frame from the instance

        # Create and add UDP tab
        self.udp_tool = UDPTool(self.notebook)
        self.notebook.add(self.udp_tool.frame, text='UDP')

        # Create and add MQTT tab - ADD THIS
        self.mqtt_tool = MQTTTool(self.notebook)
        self.notebook.add(self.mqtt_tool.frame, text='MQTT')

        # Create and add WebSocket tab
        self.websocket_tool = WebSocketTool(self.notebook)
        self.notebook.add(self.websocket_tool.frame, text='WebSocket')

        # Create and add REST tab
        try:
            if requests is not None:
                self.rest_tool = RESTClientTool(self.notebook)
                self.notebook.add(self.rest_tool.frame, text='REST')
        except Exception:
            # Fail-safe: if requests or REST UI fails to init, skip adding the tab
            pass

        # Create and add Settings tab
        try:
            self.settings_tool = SettingsTool(self.notebook)
            self.notebook.add(self.settings_tool.frame, text='Settings')
        except Exception:
            pass

        # Create and add About tab
        self.about_tool = AboutTool(self.notebook)
        self.notebook.add(self.about_tool.frame, text='About')

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # Set the most recent command after all widgets are created
        if hasattr(self.serial_tool, 'command_history') and self.serial_tool.command_history:
            self.serial_tool.send_combobox.set(self.serial_tool.command_history[-1])

    def on_tab_changed(self, event):
        """Handle tab change event - can be used for cleanup if needed."""
        # When the tab changes, we might want to perform actions related to the
        # active tab. For now, we'll keep it simple.
        pass

    def on_closing(self):
        """Handle window closing event - ensure connections are properly closed."""
        # Check if the serial_tool instance exists and is connected
        if hasattr(self, 'serial_tool') and self.serial_tool.is_connected:
            self.serial_tool.disconnect_serial()
            self.serial_tool.save_command_history()

        # Check if the tcp_client_tool instance exists and is connected
        if hasattr(self, 'tcp_client_tool') and self.tcp_client_tool.is_connected:
            self.tcp_client_tool.disconnect_client()
            self.tcp_client_tool.save_command_history()

        if hasattr(self, 'tcp_server_tool') and self.tcp_server_tool.is_running:
            self.tcp_server_tool.stop_server()

        # Check if the mqtt_tool instance exists and is connected - ADD THIS
        if hasattr(self, 'mqtt_tool') and self.mqtt_tool.is_connected:
            self.mqtt_tool.disconnect_mqtt()
            self.mqtt_tool.save_command_history()

        # Check if the websocket_tool instance exists and is connected
        if hasattr(self, 'websocket_tool') and self.websocket_tool.is_connected:
            self.websocket_tool.disconnect_ws()
            self.websocket_tool.save_command_history()

        # Check if the udp_tool instance exists and is running
        if hasattr(self, 'udp_tool') and self.udp_tool.is_running:
            self.udp_tool.stop_udp()

        # You might also want to add cleanup for TCP Server connections here later
        self.root.destroy()


class RESTClientTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.last_response = None
        self.create_widgets()

    def create_widgets(self):
        # Sub-tabs within REST: Request/Response and Chat
        self.sub_tabs = ttk.Notebook(self.frame)
        self.sub_tabs.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_columnconfigure(0, weight=1)

        rr_tab = ttk.Frame(self.sub_tabs)
        chat_tab = ttk.Frame(self.sub_tabs)
        self.sub_tabs.add(rr_tab, text='Request/Response')
        self.sub_tabs.add(chat_tab, text='Chat')

        # Request/Response tab layout with vertical PanedWindow (resizable)
        paned = ttk.PanedWindow(rr_tab, orient=tk.VERTICAL)
        paned.pack(fill='both', expand=True)

        req_frame = ttk.LabelFrame(paned, text="Request")
        resp_frame = ttk.LabelFrame(paned, text="Response")
        paned.add(req_frame, weight=3)
        paned.add(resp_frame, weight=2)

        # Toolbar (Autofill + Send) always visible at top
        toolbar = ttk.Frame(req_frame)
        toolbar.grid(row=0, column=0, columnspan=3, padx=5, pady=(6, 2), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        self.autofill_btn = ttk.Button(toolbar, text="Autofill from Docs (Gemini)", command=self.autofill_from_docs)
        self.autofill_btn.grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.edit_docs_btn = ttk.Button(toolbar, text="Edit Docs…", command=self.edit_docs_dialog)
        self.edit_docs_btn.grid(row=0, column=2, padx=(6, 0), sticky="w")
        self.send_btn = ttk.Button(toolbar, text="Send", command=self.send_request)
        self.send_btn.grid(row=0, column=1, sticky="w")

        ttk.Label(req_frame, text="Method:").grid(row=1, column=0, padx=5, pady=3, sticky="w")
        self.method_cb = ttk.Combobox(req_frame, values=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                                      state="readonly", width=10)
        self.method_cb.set("GET")
        self.method_cb.grid(row=1, column=1, padx=5, pady=3, sticky="w")

        ttk.Label(req_frame, text="URL:").grid(row=2, column=0, padx=5, pady=3, sticky="w")
        self.url_entry = ttk.Entry(req_frame, width=44)
        self.url_entry.insert(0, "https://httpbin.org/get")
        self.url_entry.grid(row=2, column=1, columnspan=2, padx=5, pady=3, sticky="ew")

        ttk.Label(req_frame, text="Params (key=value&... or lines):").grid(row=3, column=0, columnspan=3, padx=5,
                                                                           pady=(6, 2), sticky="w")
        self.params_text = scrolledtext.ScrolledText(req_frame, height=1, width=56)
        self.params_text.grid(row=4, column=0, columnspan=3, padx=5, pady=2, sticky="ew")

        ttk.Label(req_frame, text="Headers (Key: Value per line):").grid(row=5, column=0, columnspan=3, padx=5,
                                                                         pady=(6, 2), sticky="w")
        self.headers_text = scrolledtext.ScrolledText(req_frame, height=2, width=56)
        self.headers_text.insert("1.0", "User-Agent: HerculusEQ-REST\n")
        self.headers_text.grid(row=6, column=0, columnspan=3, padx=5, pady=2, sticky="ew")

        auth_frame = ttk.LabelFrame(req_frame, text="Auth")
        auth_frame.grid(row=7, column=0, columnspan=3, padx=5, pady=6, sticky="ew")
        ttk.Label(auth_frame, text="Type:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.auth_cb = ttk.Combobox(auth_frame, values=["None", "Basic", "Bearer"], state="readonly", width=10)
        self.auth_cb.set("None")
        self.auth_cb.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(auth_frame, text="Username:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.auth_user = ttk.Entry(auth_frame, width=20)
        self.auth_user.grid(row=1, column=1, padx=5, pady=2, sticky="w")
        ttk.Label(auth_frame, text="Password:").grid(row=1, column=2, padx=5, pady=2, sticky="w")
        self.auth_pass = ttk.Entry(auth_frame, width=20, show="*")
        self.auth_pass.grid(row=1, column=3, padx=5, pady=2, sticky="w")
        ttk.Label(auth_frame, text="Token:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.auth_token = ttk.Entry(auth_frame, width=44)
        self.auth_token.grid(row=2, column=1, columnspan=3, padx=5, pady=2, sticky="ew")

        body_frame = ttk.LabelFrame(req_frame, text="Body")
        body_frame.grid(row=8, column=0, columnspan=3, padx=5, pady=6, sticky="ew")
        ttk.Label(body_frame, text="Type:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.body_type_cb = ttk.Combobox(body_frame, values=["none", "raw", "json", "form-encoded", "multipart"],
                                         state="readonly", width=14)
        self.body_type_cb.set("none")
        self.body_type_cb.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.body_text = scrolledtext.ScrolledText(body_frame, height=3, width=56)
        self.body_text.grid(row=1, column=0, columnspan=4, padx=5, pady=2, sticky="ew")
        ttk.Label(body_frame, text="File field:").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        self.file_field_entry = ttk.Entry(body_frame, width=18)
        self.file_field_entry.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        ttk.Label(body_frame, text="File path:").grid(row=2, column=2, padx=5, pady=2, sticky="w")
        self.file_path_entry = ttk.Entry(body_frame, width=24)
        self.file_path_entry.grid(row=2, column=3, padx=5, pady=2, sticky="ew")
        self.file_browse_btn = ttk.Button(body_frame, text="Browse", command=self.browse_file)
        self.file_browse_btn.grid(row=2, column=4, padx=5, pady=2, sticky="w")

        opts_frame = ttk.LabelFrame(req_frame, text="Options")
        opts_frame.grid(row=9, column=0, columnspan=3, padx=5, pady=6, sticky="ew")
        ttk.Label(opts_frame, text="Timeout (s):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.timeout_entry = ttk.Entry(opts_frame, width=8)
        self.timeout_entry.insert(0, "10")
        self.timeout_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.verify_var = tk.BooleanVar(value=True)
        self.verify_chk = ttk.Checkbutton(opts_frame, text="Verify SSL", variable=self.verify_var)
        self.verify_chk.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.redirects_var = tk.BooleanVar(value=True)
        self.redirects_chk = ttk.Checkbutton(opts_frame, text="Follow redirects", variable=self.redirects_var)
        self.redirects_chk.grid(row=0, column=3, padx=5, pady=5, sticky="w")
        # API Documentation area
        docs_frame = ttk.LabelFrame(req_frame, text="API Documentation")
        docs_frame.grid(row=10, column=0, columnspan=3, padx=5, pady=6, sticky="ew")
        self.docs_text = scrolledtext.ScrolledText(docs_frame, height=4, width=56)
        self.docs_text.grid(row=0, column=0, columnspan=3, padx=5, pady=5, sticky="ew")
        # Buttons now live in toolbar at top to remain visible

        resp_frame.grid_columnconfigure(0, weight=1)
        resp_frame.grid_rowconfigure(3, weight=1)
        self.status_label = ttk.Label(resp_frame, text="Status: -")
        self.status_label.grid(row=0, column=0, padx=5, pady=4, sticky="w")
        self.time_label = ttk.Label(resp_frame, text="Time: - ms")
        self.time_label.grid(row=0, column=1, padx=5, pady=4, sticky="w")
        self.size_label = ttk.Label(resp_frame, text="Size: -")
        self.size_label.grid(row=0, column=2, padx=5, pady=4, sticky="w")
        ttk.Label(resp_frame, text="Headers:").grid(row=1, column=0, columnspan=3, padx=5, pady=(6, 2), sticky="w")
        self.resp_headers = scrolledtext.ScrolledText(resp_frame, height=6)
        self.resp_headers.grid(row=2, column=0, columnspan=3, padx=5, pady=2, sticky="nsew")
        ttk.Label(resp_frame, text="Body:").grid(row=3, column=0, columnspan=3, padx=5, pady=(6, 2), sticky="w")
        self.resp_body = scrolledtext.ScrolledText(resp_frame)
        self.resp_body.grid(row=4, column=0, columnspan=3, padx=5, pady=2, sticky="nsew")
        self.save_resp_btn = ttk.Button(resp_frame, text="Save Body", command=self.save_response_body)
        self.save_resp_btn.grid(row=5, column=2, padx=5, pady=6, sticky="e")

        # Chat area for clarifications
        # Chat tab content
        chat_frame = ttk.LabelFrame(chat_tab, text="Chat")
        chat_frame.pack(fill='both', expand=True, padx=10, pady=10)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)
        # Small toolbar in chat for quick actions
        chat_toolbar = ttk.Frame(chat_frame)
        chat_toolbar.grid(row=0, column=0, columnspan=3, padx=5, pady=(5, 2), sticky='ew')
        self.autofill_btn_chat = ttk.Button(chat_toolbar, text="Autofill from Docs (Gemini)",
                                            command=self.autofill_from_docs)
        self.autofill_btn_chat.grid(row=0, column=0, sticky='w')
        self.edit_docs_btn_chat = ttk.Button(chat_toolbar, text="Edit Docs…", command=self.edit_docs_dialog)
        self.edit_docs_btn_chat.grid(row=0, column=1, padx=8, sticky='w')
        ttk.Label(chat_toolbar, text="Docs are shared across tabs").grid(row=0, column=2, padx=8, sticky='w')

        self.chat_text = scrolledtext.ScrolledText(chat_frame, height=12, state='normal')
        self.chat_text.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="nsew")
        self.chat_entry = ttk.Entry(chat_frame)
        self.chat_entry.grid(row=2, column=0, padx=5, pady=5, sticky="ew")
        self.chat_send_btn = ttk.Button(chat_frame, text="Send Clarification", command=self.send_chat_message)
        self.chat_send_btn.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # Chat history
        self.chat_history_file = os.path.join(get_application_path(), 'rest_chat.json')
        self.chat_history = []
        self.load_chat_history()
        self.render_chat_history()

    def browse_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.file_path_entry.delete(0, tk.END)
            self.file_path_entry.insert(0, path)

    def send_request(self):
        threading.Thread(target=self._send_request_worker, daemon=True).start()

    def append_chat(self, role, text):
        self.chat_history.append({"role": role, "text": text})
        self.save_chat_history()
        self.chat_text.config(state='normal')
        prefix = "You: " if role == 'user' else "Assistant: "
        self.chat_text.insert(tk.END, f"{prefix}{text}\n")
        self.chat_text.see(tk.END)
        self.chat_text.config(state='normal')

    def send_chat_message(self):
        msg = self.chat_entry.get().strip()
        if not msg:
            return
        self.chat_entry.delete(0, tk.END)
        self.append_chat('user', msg)
        # User can press Autofill again to include this context

    def _parse_kv_text(self, text):
        data = {}
        if not text:
            return data
        if "\n" not in text and "&" in text:
            try:
                pairs = [p for p in text.split("&") if p.strip()]
                for p in pairs:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        data[k.strip()] = v.strip()
            except Exception:
                pass
            return data
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                k, v = line.split(":", 1)
            elif "=" in line:
                k, v = line.split("=", 1)
            else:
                continue
            data[k.strip()] = v.strip()
        return data

    def _merge_params(self, url, extra_params):
        try:
            parsed = urlparse(url)
            existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
            existing.update(extra_params or {})
            new_query = urlencode(existing, doseq=True)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception:
            return url

    def edit_docs_dialog(self):
        # Modal window to edit API documentation with larger area and its own scrollbar
        dlg = tk.Toplevel(self.frame)
        dlg.title("API Documentation")
        dlg.geometry("700x500")
        dlg.transient(self.frame.winfo_toplevel())
        dlg.grab_set()

        info = ttk.Label(dlg, text="Paste or edit your API documentation below. This content is used by Autofill.")
        info.pack(padx=10, pady=8, anchor='w')

        txt = scrolledtext.ScrolledText(dlg, wrap=tk.WORD)
        txt.pack(fill='both', expand=True, padx=10, pady=5)
        try:
            txt.insert('1.0', self.docs_text.get('1.0', tk.END))
        except Exception:
            pass

        btns = ttk.Frame(dlg)
        btns.pack(fill='x', padx=10, pady=8)

        def save_and_close():
            try:
                self.docs_text.delete('1.0', tk.END)
                self.docs_text.insert(tk.END, txt.get('1.0', tk.END))
            except Exception:
                pass
            dlg.destroy()

        ttk.Button(btns, text="Save", command=save_and_close).pack(side='right', padx=5)
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side='right')

    def load_chat_history(self):
        try:
            if os.path.exists(self.chat_history_file):
                with open(self.chat_history_file, 'r') as f:
                    self.chat_history = json.load(f)
        except Exception:
            self.chat_history = []

    def save_chat_history(self):
        try:
            with open(self.chat_history_file, 'w') as f:
                json.dump(self.chat_history, f, indent=2)
        except Exception:
            pass

    def render_chat_history(self):
        self.chat_text.config(state='normal')
        self.chat_text.delete('1.0', tk.END)
        for m in self.chat_history:
            prefix = "You: " if m.get('role') == 'user' else "Assistant: "
            self.chat_text.insert(tk.END, f"{prefix}{m.get('text', '')}\n")
        self.chat_text.see(tk.END)
        self.chat_text.config(state='normal')

    def autofill_from_docs(self):
        settings = load_app_settings()
        api_key = settings.get('gemini_api_key', '').strip()
        if not api_key:
            messagebox.showwarning("Gemini API Key", "Please set the Gemini API key in Settings.")
            return

        docs = self.docs_text.get('1.0', tk.END).strip()
        current_url = self.url_entry.get().strip()
        method = self.method_cb.get().strip()
        headers_text = self.headers_text.get('1.0', tk.END).strip()
        params_text = self.params_text.get('1.0', tk.END).strip()
        body_type = self.body_type_cb.get().strip()
        body_text = self.body_text.get('1.0', tk.END)

        schema = {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]},
                "url": {"type": "string"},
                "params": {"type": "object", "additionalProperties": {"type": "string"}},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "auth": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["none", "basic", "bearer"]},
                        "username": {"type": "string"},
                        "password": {"type": "string"},
                        "token": {"type": "string"}
                    },
                    "required": ["type"]
                },
                "body": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["none", "raw", "json", "form-encoded", "multipart"]},
                        "raw": {"type": "string"},
                        "json": {"type": "object"},
                        "form": {"type": "object", "additionalProperties": {"type": "string"}},
                        "multipart": {"type": "object", "additionalProperties": {"type": "string"}},
                        "file_field": {"type": "string"}
                    },
                    "required": ["type"]
                },
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "messages_to_user": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["method", "url", "params", "headers", "auth", "body"]
        }

        prompt = (
            "You are assisting in preparing an HTTP request.\n"
            "Given API documentation and the current partial request, produce only a JSON object matching the schema.\n"
            "If any required parameter or value is uncertain, add a short question in 'uncertainties'.\n"
            "If there are helpful notes for the user, add them in 'messages_to_user'.\n"
            f"API documentation:\n{docs}\n\n"
            f"Current request state:\nMethod: {method}\nURL: {current_url}\nHeaders:\n{headers_text}\nParams:\n{params_text}\nBody type: {body_type}\nBody:\n{body_text}\n\n"
            f"JSON schema (for reference):\n{json.dumps(schema)}\n"
            "Return ONLY the JSON, no markdown or extra text."
        )

        contents = []
        for m in self.chat_history:
            role = 'user' if m.get('role') == 'user' else 'model'
            contents.append({"role": role, "parts": [{"text": m.get('text', '')}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        try:
            resp = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json={
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json"
                    }
                },
                timeout=20
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            if not text:
                raise Exception("Empty response from Gemini")
            self.append_chat('assistant', text)

            try:
                payload = json.loads(text)
            except Exception as e:
                messagebox.showerror("Gemini", f"Failed to parse JSON from model:\n{text}\nError: {e}")
                return

            self._apply_autofill_payload(payload)

            uncertainties = payload.get('uncertainties') or []
            messages_to_user = payload.get('messages_to_user') or []
            if uncertainties:
                self.append_chat('assistant', "Questions/uncertainties: " + "; ".join(uncertainties))
            for msg in messages_to_user:
                self.append_chat('assistant', msg)

        except Exception as e:
            messagebox.showerror("Gemini", f"Autofill failed:\n{e}")

    def _apply_autofill_payload(self, p):
        try:
            method = p.get('method')
            if method in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
                self.method_cb.set(method)
        except Exception:
            pass
        try:
            url = p.get('url')
            if url:
                self.url_entry.delete(0, tk.END)
                self.url_entry.insert(0, url)
        except Exception:
            pass
        try:
            params = p.get('params') or {}
            if isinstance(params, dict):
                lines = [f"{k}={v}" for k, v in params.items()]
                self.params_text.delete('1.0', tk.END)
                self.params_text.insert(tk.END, "\n".join(lines))
        except Exception:
            pass
        try:
            headers = p.get('headers') or {}
            if isinstance(headers, dict):
                lines = [f"{k}: {v}" for k, v in headers.items()]
                self.headers_text.delete('1.0', tk.END)
                self.headers_text.insert(tk.END, "\n".join(lines))
        except Exception:
            pass
        try:
            auth = p.get('auth') or {}
            atype = (auth.get('type') or 'none').lower()
            if atype == 'basic':
                self.auth_cb.set('Basic')
                self.auth_user.delete(0, tk.END)
                self.auth_user.insert(0, auth.get('username', ''))
                self.auth_pass.delete(0, tk.END)
                self.auth_pass.insert(0, auth.get('password', ''))
            elif atype == 'bearer':
                self.auth_cb.set('Bearer')
                self.auth_token.delete(0, tk.END)
                self.auth_token.insert(0, auth.get('token', ''))
            else:
                self.auth_cb.set('None')
        except Exception:
            pass
        try:
            body = p.get('body') or {}
            btype = (body.get('type') or 'none')
            if btype in ["none", "raw", "json", "form-encoded", "multipart"]:
                self.body_type_cb.set(btype)
            if btype == 'raw':
                self.body_text.delete('1.0', tk.END)
                self.body_text.insert(tk.END, body.get('raw', ''))
            elif btype == 'json':
                self.body_text.delete('1.0', tk.END)
                try:
                    self.body_text.insert(tk.END, json.dumps(body.get('json') or {}, indent=2))
                except Exception:
                    self.body_text.insert(tk.END, '{}')
            elif btype == 'form-encoded':
                self.body_text.delete('1.0', tk.END)
                form = body.get('form') or {}
                lines = [f"{k}={v}" for k, v in form.items()]
                self.body_text.insert(tk.END, "\n".join(lines))
            elif btype == 'multipart':
                self.body_text.delete('1.0', tk.END)
                mp = body.get('multipart') or {}
                lines = [f"{k}={v}" for k, v in mp.items()]
                self.body_text.insert(tk.END, "\n".join(lines))
                if body.get('file_field'):
                    self.file_field_entry.delete(0, tk.END)
                    self.file_field_entry.insert(0, body.get('file_field'))
        except Exception:
            pass

    def _send_request_worker(self):
        method = self.method_cb.get().strip().upper()
        url = self.url_entry.get().strip()
        params_text = self.params_text.get("1.0", tk.END).strip()
        headers_text = self.headers_text.get("1.0", tk.END).strip()
        body_type = self.body_type_cb.get().strip()
        body_text = self.body_text.get("1.0", tk.END)
        timeout = 10.0
        try:
            timeout = float(self.timeout_entry.get().strip())
        except Exception:
            pass
        verify = bool(self.verify_var.get())
        allow_redirects = bool(self.redirects_var.get())
        headers = self._parse_kv_text(headers_text)
        auth = None
        auth_type = self.auth_cb.get().strip()
        if auth_type == "Basic":
            auth = (self.auth_user.get(), self.auth_pass.get())
        elif auth_type == "Bearer":
            token = self.auth_token.get().strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        params = self._parse_kv_text(params_text)
        url = self._merge_params(url, params)
        data = None
        json_data = None
        files = None
        try:
            if body_type == "json":
                if body_text.strip():
                    json_data = json.loads(body_text)
            elif body_type == "form-encoded":
                data = self._parse_kv_text(body_text)
            elif body_type == "multipart":
                data = self._parse_kv_text(body_text)
                field = self.file_field_entry.get().strip()
                fpath = self.file_path_entry.get().strip()
                if field and fpath and os.path.isfile(fpath):
                    files = {field: open(fpath, 'rb')}
            elif body_type == "raw":
                data = body_text
        except Exception as e:
            self._update_response_error(f"Body parse error: {e}")
            return
        start = time.perf_counter()
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers or None,
                data=data if isinstance(data, (str, bytes, dict)) else None,
                json=json_data,
                files=files,
                timeout=timeout,
                verify=verify,
                allow_redirects=allow_redirects,
                auth=auth,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            self.last_response = resp
            self._update_response_success(resp, elapsed_ms)
        except Exception as e:
            self._update_response_error(str(e))
        finally:
            try:
                if files:
                    for f in files.values():
                        try:
                            f.close()
                        except Exception:
                            pass
            except Exception:
                pass

    def _update_response_success(self, resp, elapsed_ms):
        def ui():
            self.status_label.config(text=f"Status: {resp.status_code}")
            self.time_label.config(text=f"Time: {elapsed_ms} ms")
            size = len(resp.content) if resp.content is not None else 0
            self.size_label.config(text=f"Size: {size} bytes")
            self.resp_headers.config(state='normal')
            self.resp_headers.delete('1.0', tk.END)
            for k, v in resp.headers.items():
                self.resp_headers.insert(tk.END, f"{k}: {v}\n")
            self.resp_headers.config(state='normal')
            text = None
            try:
                if 'application/json' in resp.headers.get('Content-Type', '').lower():
                    text = json.dumps(resp.json(), indent=2, ensure_ascii=False)
                else:
                    text = resp.text
            except Exception:
                text = resp.text
            self.resp_body.config(state='normal')
            self.resp_body.delete('1.0', tk.END)
            if text is not None:
                self.resp_body.insert(tk.END, text)
            self.resp_body.config(state='normal')

        self.frame.after(0, ui)

    def _update_response_error(self, message):
        def ui():
            self.status_label.config(text=f"Status: ERROR")
            self.time_label.config(text=f"Time: - ms")
            self.size_label.config(text=f"Size: -")
            self.resp_headers.config(state='normal')
            self.resp_headers.delete('1.0', tk.END)
            self.resp_body.config(state='normal')
            self.resp_body.delete('1.0', tk.END)
            self.resp_body.insert(tk.END, message)

        self.frame.after(0, ui)

    def save_response_body(self):
        if not self.last_response:
            messagebox.showinfo("Save Body", "No response available to save.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("All Files", "*.*"), ("Text", ".txt")])
        if not path:
            return
        try:
            with open(path, 'wb') as f:
                f.write(self.last_response.content)
            messagebox.showinfo("Save Body", f"Saved to {path}")
        except Exception as e:
            messagebox.showerror("Save Body", f"Failed to save body:\n{e}")


class SettingsTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.create_widgets()

    def create_widgets(self):
        settings = load_app_settings()

        api_frame = ttk.LabelFrame(self.frame, text="Gemini API Settings")
        api_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")
        ttk.Label(api_frame, text="Gemini API Key:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.api_key_entry = ttk.Entry(api_frame, width=50, show='*')
        self.api_key_entry.insert(0, settings.get('gemini_api_key', ''))
        self.api_key_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.save_btn = ttk.Button(api_frame, text="Save", command=self.save_settings)
        self.save_btn.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        self.status_label = ttk.Label(api_frame, text="")
        self.status_label.grid(row=1, column=0, columnspan=3, padx=5, pady=5, sticky="w")

    def save_settings(self):
        key = self.api_key_entry.get().strip()
        data = load_app_settings()
        data['gemini_api_key'] = key
        ok = save_app_settings(data)
        if ok:
            self.status_label.config(text="Saved.", foreground='green')
        else:
            self.status_label.config(text="Failed to save.", foreground='red')


if __name__ == "__main__":
    # If running from source (e.g., in a terminal that inherited vars from a PyInstaller app)
    # we need to clear out any leftover _MEI temp paths from TCL/TK libraries
    if not getattr(sys, 'frozen', False):
        for env_var in ['TCL_LIBRARY', 'TK_LIBRARY']:
            if env_var in os.environ and '_MEI' in os.environ[env_var]:
                del os.environ[env_var]
                
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()