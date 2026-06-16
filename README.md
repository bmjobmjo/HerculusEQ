# HerculusEQ

**HerculusEQ** is a comprehensive, multi-protocol desktop testing utility designed for developers, hardware engineers, and IoT integrators. Built with Python and Tkinter, it provides a modern, unified interface for debugging and communicating across a variety of hardware interfaces and network protocols. It can be considered as a modern, multi-protocol distant equivalent of the classic [Hercules SETUP utility](https://www.hw-group.com/software/hercules-setup-utility).

## 🚀 Features

HerculusEQ offers dedicated tool tabs for different communication protocols:

### 📡 Serial Port Terminal
- Connect to local COM ports with customizable baud rates, data bits, parity, and stop bits.
- Real-time monitoring of incoming and outgoing data.
- View data in both ASCII and Hexadecimal formats.
- Save received data streams directly to local files.

### 🌐 TCP Client & Server
- **TCP Client**: Connect to remote TCP servers, send custom payloads, and monitor responses.
- **TCP Server**: Host a local TCP server to listen for incoming connections and interact with connected clients.

### 🚀 UDP Terminal
- Send and receive connectionless UDP datagrams.
- Bind to local ports to listen for incoming UDP traffic.

### 📨 MQTT Client
- Connect to MQTT brokers (supports authentication and custom client IDs).
- Subscribe to multiple topics.
- Publish payloads to specific topics for robust IoT testing.

### 🔗 WebSocket Client
- Connect to remote WebSocket (WS/WSS) endpoints.
- Exchange real-time WebSocket frames effortlessly.

## ✨ Advanced User Interface

HerculusEQ is designed for efficiency and ease of use:
- **Big Edit Box**: A pop-up multi-line text editor for drafting large or complex payloads before sending them.
- **Command History**: Every tool remembers your last 500 commands. Your history is automatically saved locally across sessions!
- **Interactive Selection**: Quickly recall previous commands via interactive dropdowns and clickable history listboxes.
- **Auto-Scroll & Clear**: Manage your terminal views with quick clear buttons and auto-scrolling toggles.

## 🛠️ Installation & Setup

### Prerequisites
- **Python 3.7+** installed on your system.

### Dependencies
Install the required Python libraries using pip:

```bash
pip install pyserial paho-mqtt websocket-client requests
```

### Running the Application

To launch HerculusEQ, simply execute the main Python script:

```bash
python HerculusEQ_claude.py
```

## 📂 Project Structure

- `HerculusEQ_claude.py`: The main entry point, containing the Core UI, Serial, TCP, and UDP tools.
- `Mqtt_too.py`: The MQTT Client implementation.
- `Websocket_tool.py`: The WebSocket Client implementation.
- `*_commands.json` / `*_settings.json`: Automatically generated files that persist your command history and connection settings locally.

## 🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page or submit a Pull Request.

## 📝 License
This project is open-source. Feel free to use, modify, and distribute as needed.
