import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import serial
import serial.tools.list_ports
import threading
import time
import os
import json

from Mqtt_too import MQTTTool


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

        # Option to add timestamp to received data
        self.timestamp_var = tk.BooleanVar(value=False)

        # Added to store all received data and the filter text
        self.all_received_data = ""
        self.filter_text = ""

        # Initialize command history before creating widgets
        self.command_history = []
        self.command_history_file = "last_commands.json"
        self.max_history = 20  # Increased to store more commands
        self.load_command_history()

        self.create_widgets()

    def create_widgets(self):
        # Frame for Serial Port Configuration
        config_frame = ttk.LabelFrame(self.frame, text="Serial Port Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        # Port Selection
        ttk.Label(config_frame, text="Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_combobox = ttk.Combobox(config_frame, state="readonly")
        self.port_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.list_ports()
        self.port_combobox.bind("<<ComboboxSelected>>", self.on_port_selected)

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

        # Connect/Disconnect Button
        self.connect_button = ttk.Button(config_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=5, column=0, columnspan=2, padx=5, pady=10)

        # Frame for Received Data
        received_frame = ttk.LabelFrame(self.frame, text="Received Data")
        received_frame.grid(row=0, column=1, rowspan=3, padx=10, pady=10, sticky="nsew")
        self.frame.grid_columnconfigure(1, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=0)
        self.frame.grid_rowconfigure(2, weight=0)

        # Buffer limit control
        limit_frame = ttk.Frame(received_frame)
        limit_frame.pack(pady=(5, 0), fill=tk.X)
        ttk.Label(limit_frame, text="Max Chars:").pack(side=tk.LEFT, padx=(5, 0))
        self.buffer_limit_var = tk.StringVar(value="20000")
        self.buffer_limit = 20000
        self.buffer_limit_var.trace_add("write", lambda *args: self.on_buffer_limit_changed())
        self.buffer_limit_entry = ttk.Entry(limit_frame, textvariable=self.buffer_limit_var, width=10)
        self.buffer_limit_entry.pack(side=tk.LEFT, padx=5)

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

        # History button (now shows history in separate window)
        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=2, padx=5, pady=5)

        # HEX Send Checkbox
        self.send_hex_var = tk.BooleanVar()
        self.send_hex_checkbox = ttk.Checkbutton(send_frame, text="Send as HEX", variable=self.send_hex_var)
        self.send_hex_checkbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Timestamp Checkbox
        self.timestamp_checkbox = ttk.Checkbutton(send_frame, text="Add Timestamp", variable=self.timestamp_var)
        self.timestamp_checkbox.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Status Label (placed below the frames)
        self.status_label = ttk.Label(self.frame, text="", anchor="w")
        self.status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Update combobox with initial history
        self.update_combobox_values()

    def on_combobox_key_release(self, event):
        """Handle key release events in the combobox for better user experience."""
        # Allow normal typing behavior while maintaining dropdown functionality
        pass

    def update_combobox_values(self, event=None):
        """Update the combobox dropdown with current command history."""
        # Reverse the history so most recent commands appear at the top
        reversed_history = list(reversed(self.command_history))
        self.send_combobox['values'] = reversed_history

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

        # Create text widget with scrollbar
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(expand=True, fill="both")

        text_widget = tk.Text(text_frame, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")

        # Insert history (most recent first)
        reversed_history = list(reversed(self.command_history))
        for i, cmd in enumerate(reversed_history, 1):
            text_widget.insert(tk.END, f"{i:2d}. {cmd}\n")

        text_widget.config(state='disabled')  # Make read-only

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        ttk.Button(button_frame, text="Clear History", command=lambda: self.clear_command_history(history_window)).pack(
            side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=history_window.destroy).pack(side="left")

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

        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=data_size,
                parity=parity,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
                rtscts=rtscts,
                xonxoff=xonxoff
            )
            self.is_connected = True
            self.connect_button.config(text="Disconnect")
            self.pause_button.config(state=tk.NORMAL)
            self.update_status(f"Connected to {port}", "green")

            self.stop_event.clear()
            self.pause_event.clear()
            self.reading_thread = threading.Thread(target=self.read_from_port)
            self.reading_thread.daemon = True
            self.reading_thread.start()

        except serial.SerialException as e:
            messagebox.showerror("Connection Error", f"Could not connect to port {port}:\n{e}")
            self.is_connected = False
            self.pause_button.config(state=tk.DISABLED)
            self.update_status("", "black")  # Clear status on error

    def disconnect_serial(self):
        """Disconnects from the serial port."""
        if self.serial_port and self.serial_port.isOpen():
            self.stop_event.set()
            self.pause_event.clear()
            if self.is_saving:
                self.toggle_saving()

            if self.reading_thread and self.reading_thread.is_alive():
                self.reading_thread.join(timeout=1.0)

            self.serial_port.close()
            self.is_connected = False
            self.connect_button.config(text="Connect")
            self.pause_button.config(text="Pause", state=tk.DISABLED)
            self.update_status(f"Disconnected from {self.serial_port.port}", "red")

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

    def read_from_port(self):
        """Reads data from the serial port in a separate thread."""
        while not self.stop_event.is_set() and self.serial_port and self.serial_port.isOpen():
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue

            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    try:
                        decoded_data = data.decode('utf-8', errors='replace')
                    except UnicodeDecodeError:
                        decoded_data = data.decode('latin-1', errors='replace')

                    if self.timestamp_var.get():
                        timestamp = time.strftime("%H:%M:%S")
                        decoded_data = f"[{timestamp}] {decoded_data}"

                    # Append new data to the full received data storage
                    self.all_received_data += decoded_data
                    self.trim_received_data()
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

    def get_buffer_limit(self):
        """Return the maximum number of characters to keep in memory."""
        return self.buffer_limit

    def trim_received_data(self):
        """Trim stored data to keep memory usage bounded."""
        limit = self.get_buffer_limit()
        if limit > 0 and len(self.all_received_data) > limit:
            excess = len(self.all_received_data) - limit
            self.all_received_data = self.all_received_data[excess:]

    def on_buffer_limit_changed(self):
        """Callback when buffer limit entry is modified."""
        try:
            self.buffer_limit = int(self.buffer_limit_var.get())
        except ValueError:
            # Revert to previous valid value if parsing fails
            self.buffer_limit_var.set(str(self.buffer_limit))
            return
        self.trim_received_data()
        self.apply_filter()

    def clear_received_text(self):
        """Clears the received data text area and the stored data."""
        self.received_text.config(state='normal')
        self.received_text.delete('1.0', tk.END)
        self.received_text.config(state='disabled')
        self.all_received_data = ""  # Also clear the stored data
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

        # Option to add timestamp to received data
        self.timestamp_var = tk.BooleanVar(value=False)

        # Store all received data and filter text
        self.all_received_data = ""
        self.filter_text = ""

        # Connection type (TCP or UDP)
        self.connection_type = "TCP"

        # Initialize command history before creating widgets
        self.command_history = []
        self.command_history_file = "tcp_commands.json"
        self.max_history = 20
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

        # History button
        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=2, padx=5, pady=5)

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

        text_frame = ttk.Frame(main_frame)
        text_frame.pack(expand=True, fill="both")

        text_widget = tk.Text(text_frame, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side="left", expand=True, fill="both")
        scrollbar.pack(side="right", fill="y")

        reversed_history = list(reversed(self.command_history))
        for i, cmd in enumerate(reversed_history, 1):
            text_widget.insert(tk.END, f"{i:2d}. {cmd}\n")

        text_widget.config(state='disabled')

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10, 0))

        ttk.Button(button_frame, text="Clear History", command=lambda: self.clear_command_history(history_window)).pack(
            side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Close", command=history_window.destroy).pack(side="left")

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

                if self.timestamp_var.get():
                    timestamp = time.strftime("%H:%M:%S")
                    decoded_data = f"[{timestamp}] {decoded_data}"

                self.all_received_data += decoded_data
                self.notebook.winfo_toplevel().after(0, self.process_received_data, decoded_data)

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
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")
        ttk.Label(self.frame, text="TCP Server functionality will go here.").pack()
        # Add TCP Server specific widgets and logic later


class MainApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("Communication Tool")
        self.root.geometry("750x650")

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

        # Create and add MQTT tab - ADD THIS
        self.mqtt_tool = MQTTTool(self.notebook)
        self.notebook.add(self.mqtt_tool.frame, text='MQTT')

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

        # Check if the mqtt_tool instance exists and is connected - ADD THIS
        if hasattr(self, 'mqtt_tool') and self.mqtt_tool.is_connected:
            self.mqtt_tool.disconnect_mqtt()
            self.mqtt_tool.save_command_history()

        # You might also want to add cleanup for TCP Server connections here later
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MainApplication(root)
    root.mainloop()