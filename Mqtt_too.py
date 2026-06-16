import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import time
import os
import json
import sys
import paho.mqtt.client as mqtt

def get_application_path():
    """Get the path to the application directory (works for dev and frozen/onefile)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class MQTTTool:
    def __init__(self, notebook):
        self.notebook = notebook
        self.frame = ttk.Frame(notebook, padding="10")
        self.frame.pack(expand=True, fill="both")

        self.mqtt_client = None
        self.is_connected = False
        self.pause_event = threading.Event()

        self.saving_file = None
        self.is_saving = False

        # Added to store all received data and the filter text
        self.all_received_data = ""
        self.filter_text = ""

        # Initialize command history before creating widgets
        self.command_history = []
        self.command_history_file = os.path.join(get_application_path(), "mqtt_commands.json")
        self.max_history = 20
        self.load_command_history()

        # MQTT specific variables
        self.subscribed_topics = []
        self.settings_file = os.path.join(get_application_path(), "mqtt_settings.json")

        self.create_widgets()
        self.load_settings()

    def create_widgets(self):
        # Frame for MQTT Configuration
        config_frame = ttk.LabelFrame(self.frame, text="MQTT Configuration")
        config_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        # Broker Server
        ttk.Label(config_frame, text="Broker:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.broker_entry = ttk.Entry(config_frame, width=20)
        self.broker_entry.insert(0, "broker.mqtt-dashboard.com")  # Default public broker
        self.broker_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Port
        ttk.Label(config_frame, text="Port:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.port_entry = ttk.Entry(config_frame, width=20)
        self.port_entry.insert(0, "1883")  # Default MQTT port
        self.port_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Client ID
        ttk.Label(config_frame, text="Client ID:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.client_id_entry = ttk.Entry(config_frame, width=20)
        self.client_id_entry.insert(0, f"client_{int(time.time())}")  # Unique client ID
        self.client_id_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Username (optional)
        ttk.Label(config_frame, text="Username:").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.username_entry = ttk.Entry(config_frame, width=20)
        self.username_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")

        # Password (optional)
        ttk.Label(config_frame, text="Password:").grid(row=4, column=0, padx=5, pady=5, sticky="w")
        self.password_entry = ttk.Entry(config_frame, width=20, show="*")
        self.password_entry.grid(row=4, column=1, padx=5, pady=5, sticky="ew")

        # Subscribe Topic
        ttk.Label(config_frame, text="In Topic:").grid(row=5, column=0, padx=5, pady=5, sticky="w")
        self.in_topic_entry = ttk.Entry(config_frame, width=20)
        self.in_topic_entry.insert(0, "test/in")  # Default topic
        self.in_topic_entry.grid(row=5, column=1, padx=5, pady=5, sticky="ew")

        # Publish Topic
        ttk.Label(config_frame, text="Out Topic:").grid(row=6, column=0, padx=5, pady=5, sticky="w")
        self.out_topic_entry = ttk.Entry(config_frame, width=20)
        self.out_topic_entry.insert(0, "test/out")  # Default topic
        self.out_topic_entry.grid(row=6, column=1, padx=5, pady=5, sticky="ew")

        # QoS Selection
        ttk.Label(config_frame, text="QoS:").grid(row=7, column=0, padx=5, pady=5, sticky="w")
        self.qos_combobox = ttk.Combobox(config_frame, values=["0", "1", "2"], state="readonly", width=17)
        self.qos_combobox.set("0")
        self.qos_combobox.grid(row=7, column=1, padx=5, pady=5, sticky="ew")

        # Connect/Disconnect Button
        self.connect_button = ttk.Button(config_frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=8, column=0, columnspan=2, padx=5, pady=10)

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
        send_frame = ttk.LabelFrame(self.frame, text="Publish Message")
        send_frame.grid(row=1, column=0, padx=10, pady=10, sticky="sw")

        # Message input with history
        self.send_combobox = ttk.Combobox(send_frame, width=37)
        self.send_combobox.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.send_combobox.bind("<Return>", lambda event=None: self.send_data())
        self.send_combobox.bind("<KeyRelease>", self.on_combobox_key_release)
        self.send_combobox.bind("<Button-1>", self.update_combobox_values)

        self.send_button = ttk.Button(send_frame, text="Publish", command=self.send_data)
        self.send_button.grid(row=0, column=1, padx=5, pady=5)

        # History button
        self.history_button = ttk.Button(send_frame, text="History", command=self.show_command_history)
        self.history_button.grid(row=0, column=2, padx=5, pady=5)

        # JSON Format Checkbox
        self.send_json_var = tk.BooleanVar()
        self.send_json_checkbox = ttk.Checkbutton(send_frame, text="Format as JSON", variable=self.send_json_var)
        self.send_json_checkbox.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky="w")

        # Status Label
        self.status_label = ttk.Label(self.frame, text="", anchor="w")
        self.status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="ew")

        # Update combobox with initial history
        self.update_combobox_values()

    def load_settings(self):
        """Load saved MQTT settings from JSON file."""
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)

                # Clear and insert settings
                self.broker_entry.delete(0, tk.END)
                self.broker_entry.insert(0, settings.get("broker", ""))

                self.port_entry.delete(0, tk.END)
                self.port_entry.insert(0, settings.get("port", "1883"))

                self.client_id_entry.delete(0, tk.END)
                self.client_id_entry.insert(0, settings.get("client_id", ""))

                self.username_entry.delete(0, tk.END)
                self.username_entry.insert(0, settings.get("username", ""))

                self.password_entry.delete(0, tk.END)
                self.password_entry.insert(0, settings.get("password", ""))

                self.in_topic_entry.delete(0, tk.END)
                self.in_topic_entry.insert(0, settings.get("in_topic", ""))

                self.out_topic_entry.delete(0, tk.END)
                self.out_topic_entry.insert(0, settings.get("out_topic", ""))

                self.qos_combobox.set(settings.get("qos", "0"))

            except Exception as e:
                print(f"Failed to load MQTT settings: {e}")

    def save_settings(self):
        """Save MQTT settings to a JSON file."""
        settings = {
            "broker": self.broker_entry.get().strip(),
            "port": self.port_entry.get().strip(),
            "client_id": self.client_id_entry.get().strip(),
            "username": self.username_entry.get().strip(),
            "password": self.password_entry.get().strip(),
            "in_topic": self.in_topic_entry.get().strip(),
            "out_topic": self.out_topic_entry.get().strip(),
            "qos": self.qos_combobox.get()
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save MQTT settings: {e}")

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

        ttk.Label(main_frame, text="Recent Messages (most recent first):").pack(anchor="w", pady=(0, 5))

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
        result = messagebox.askyesno("Clear History", "Are you sure you want to clear all message history?",
                                     parent=window)
        if result:
            self.command_history = []
            self.save_command_history()
            self.update_combobox_values()
            window.destroy()
            messagebox.showinfo("History Cleared", "Message history has been cleared.")

    def load_command_history(self):
        """Load command history from file."""
        if os.path.exists(self.command_history_file):
            try:
                with open(self.command_history_file, "r") as f:
                    self.command_history = json.load(f)
            except Exception as e:
                print(f"Failed to load message history: {e}")
                self.command_history = []

    def save_command_history(self):
        """Save command history to file."""
        try:
            history_to_save = self.command_history[-self.max_history:]
            with open(self.command_history_file, "w") as f:
                json.dump(history_to_save, f, indent=2)
        except Exception as e:
            print(f"Failed to save message history: {e}")

    def toggle_connection(self):
        """Connect or disconnect from the MQTT broker."""
        if self.is_connected:
            self.disconnect_mqtt()
        else:
            self.connect_mqtt()

    def on_connect(self, client, userdata, flags, rc):
        """Callback for when the client receives a CONNACK response from the server."""
        if rc == 0:
            self.notebook.winfo_toplevel().after(0, self.on_connection_success)
            # Subscribe to the in topic
            in_topic = self.in_topic_entry.get().strip()
            if in_topic:
                qos = int(self.qos_combobox.get())
                client.subscribe(in_topic, qos)
                self.subscribed_topics.append(in_topic)
        else:
            error_msg = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorised"
            }.get(rc, f"Connection refused - return code {rc}")
            self.notebook.winfo_toplevel().after(0, self.on_connection_failed, error_msg)

    def on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the server."""
        if rc != 0:
            self.notebook.winfo_toplevel().after(0, self.on_unexpected_disconnect)

    def on_message(self, client, userdata, msg):
        """Callback for when a PUBLISH message is received from the server."""
        try:
            # Decode the message payload
            payload = msg.payload.decode('utf-8', errors='replace')

            # Format the message with timestamp and topic
            timestamp = time.strftime("%H:%M:%S")
            formatted_message = f"[{timestamp}] [{msg.topic}] {payload}\n"

            # Process the message in the main thread
            self.notebook.winfo_toplevel().after(0, self.process_received_message, formatted_message)
        except Exception as e:
            print(f"Error processing message: {e}")

    def on_connection_success(self):
        """Handle successful connection."""
        self.is_connected = True
        self.connect_button.config(text="Disconnect")
        self.pause_button.config(state=tk.NORMAL)

        # Disable configuration fields while connected
        self.broker_entry.config(state="disabled")
        self.port_entry.config(state="disabled")
        self.client_id_entry.config(state="disabled")
        self.username_entry.config(state="disabled")
        self.password_entry.config(state="disabled")
        self.in_topic_entry.config(state="disabled")
        self.out_topic_entry.config(state="disabled")
        self.qos_combobox.config(state="disabled")

        broker = self.broker_entry.get()
        port = self.port_entry.get()
        self.update_status(f"Connected to {broker}:{port}", "green")

        # ✅ Save only after successful connect
        self.save_settings()

    def on_connection_failed(self, error_msg):
        """Handle failed connection."""
        messagebox.showerror("Connection Error", error_msg)
        self.is_connected = False
        self.update_status("", "black")

    def on_unexpected_disconnect(self):
        """Handle unexpected disconnection."""
        self.disconnect_mqtt()
        self.update_status("Unexpectedly disconnected", "red")

    def connect_mqtt(self):
        """Connect to the MQTT broker."""
        try:
            broker = self.broker_entry.get().strip()
            port = int(self.port_entry.get().strip())
            client_id = self.client_id_entry.get().strip()
            username = self.username_entry.get().strip()
            password = self.password_entry.get().strip()

            if not broker or not port:
                messagebox.showwarning("Connection Error", "Please enter broker address and port.")
                return

            # Create MQTT client
            self.mqtt_client = mqtt.Client(client_id=client_id)

            # Set callbacks
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect

            # Set credentials if provided
            if username:
                self.mqtt_client.username_pw_set(username, password)

            # Connect to the broker
            self.mqtt_client.connect(broker, port, keepalive=60)

            # Start the network loop in a separate thread
            self.mqtt_client.loop_start()

            self.pause_event.clear()

        except ValueError:
            messagebox.showerror("Connection Error", "Invalid port number.")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Could not connect to broker:\n{e}")
            self.is_connected = False
            self.pause_button.config(state=tk.DISABLED)
            self.update_status("", "black")

    def disconnect_mqtt(self):
        """Disconnect from the MQTT broker."""
        self.save_settings()
        if self.mqtt_client:
            self.pause_event.clear()
            if self.is_saving:
                self.toggle_saving()

            # Unsubscribe from all topics
            for topic in self.subscribed_topics:
                self.mqtt_client.unsubscribe(topic)
            self.subscribed_topics.clear()

            # Stop the network loop and disconnect
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

            self.mqtt_client = None
            self.is_connected = False
            self.connect_button.config(text="Connect")
            self.pause_button.config(text="Pause", state=tk.DISABLED)

            # Re-enable configuration fields
            self.broker_entry.config(state="normal")
            self.port_entry.config(state="normal")
            self.client_id_entry.config(state="normal")
            self.username_entry.config(state="normal")
            self.password_entry.config(state="normal")
            self.in_topic_entry.config(state="normal")
            self.out_topic_entry.config(state="normal")
            self.qos_combobox.config(state="readonly")

            self.update_status("Disconnected", "red")

    def toggle_pause(self):
        """Toggle pausing and resuming the message display."""
        if self.is_connected:
            if self.pause_event.is_set():
                self.pause_event.clear()
                self.pause_button.config(text="Pause")
                if self.is_saving:
                    self.update_status(f"Connected & Saving (MQTT)", "blue")
                else:
                    broker = self.broker_entry.get()
                    port = self.port_entry.get()
                    self.update_status(f"Connected to {broker}:{port}", "green")
            else:
                self.pause_event.set()
                self.pause_button.config(text="Resume")
                self.update_status("Paused (MQTT)", "orange")

    def process_received_message(self, message):
        """Process received MQTT message."""
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
                broker = self.broker_entry.get()
                port = self.port_entry.get()
                self.update_status(f"Connected to {broker}:{port}", "green")
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
                    self.update_status(f"Connected & Saving (MQTT)", "blue")
            except Exception as e:
                messagebox.showerror("Saving Error", f"Could not open file for saving:\n{e}")
                self.is_saving = False
                if self.saving_file:
                    self.saving_file.close()
                    self.saving_file = None

    def send_data(self):
        """Publish message to MQTT broker."""
        msg = self.send_combobox.get().strip()

        # Add message to history
        if msg and (not self.command_history or self.command_history[-1] != msg):
            self.command_history.append(msg)
            if len(self.command_history) > self.max_history:
                self.command_history = self.command_history[-self.max_history:]
            self.save_command_history()
            self.update_combobox_values()

        if self.mqtt_client and self.is_connected:
            message = self.send_combobox.get()
            out_topic = self.out_topic_entry.get().strip()
            qos = int(self.qos_combobox.get())

            if not out_topic:
                messagebox.showwarning("Publish Error", "Please specify an output topic.")
                return

            if self.send_json_var.get():
                # Try to format as JSON if checkbox is selected
                try:
                    # Try to parse as JSON to validate
                    json_data = json.loads(message)
                    # Convert back to string with proper formatting
                    message = json.dumps(json_data)
                except json.JSONDecodeError:
                    # If not valid JSON, try to create a simple JSON object
                    try:
                        message = json.dumps({"message": message})
                    except Exception:
                        messagebox.showerror("JSON Error", "Could not format message as JSON.")
                        return

            try:
                result = self.mqtt_client.publish(out_topic, message, qos=qos)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    # Clear the combobox after successful send
                    self.send_combobox.set("")

                    # Also display sent message in the received area with a different format
                    timestamp = time.strftime("%H:%M:%S")
                    sent_message = f"[{timestamp}] [SENT -> {out_topic}] {message}\n"
                    self.process_received_message(sent_message)
                else:
                    messagebox.showerror("Publish Error", f"Failed to publish message. Error code: {result.rc}")
            except Exception as e:
                messagebox.showerror("Publish Error", f"Could not publish message:\n{e}")
        else:
            messagebox.showwarning("Not Connected", "Please connect to an MQTT broker first.")

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