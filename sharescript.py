#!/usr/bin/env python3
"""
Shared Terminal Web Service with Full Terminal Emulation
A service that provides a shared terminal interface with proper ANSI handling.
"""

import os
import pty
import select
import subprocess
import threading
import time
import base64
from datetime import datetime
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
import signal
import sys

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
class TerminalState:
    def __init__(self):
        self.is_running = False
        self.process = None
        self.master_fd = None
        self.lock = threading.Lock()
        # Store raw terminal data for proper terminal emulation
        self.terminal_data = b''
        
    def add_data(self, data):
        """Add raw terminal data (bytes)"""
        with self.lock:
            self.terminal_data += data
            # Keep only last 1MB to prevent memory issues
            if len(self.terminal_data) > 1024 * 1024:
                # Keep last 512KB
                self.terminal_data = self.terminal_data[-512*1024:]
    
    def get_terminal_data(self):
        """Get all terminal data as base64 for transmission"""
        with self.lock:
            return base64.b64encode(self.terminal_data).decode('ascii')
    
    def clear_data(self):
        with self.lock:
            self.terminal_data = b''

terminal_state = TerminalState()

# HTML template with xterm.js
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Shared Terminal - foobar.sh Runner</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/xterm/4.19.0/xterm.min.css" />
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #1e1e1e;
            color: #ffffff;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #4CAF50;
            text-align: center;
            margin-bottom: 20px;
        }
        .controls {
            text-align: center;
            margin-bottom: 20px;
        }
        .btn {
            padding: 10px 20px;
            font-size: 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin: 0 10px;
        }
        .btn-primary {
            background-color: #4CAF50;
            color: white;
        }
        .btn-primary:hover:not(:disabled) {
            background-color: #45a049;
        }
        .btn-secondary {
            background-color: #f44336;
            color: white;
        }
        .btn-secondary:hover:not(:disabled) {
            background-color: #da190b;
        }
        .btn:disabled {
            background-color: #cccccc;
            color: #666666;
            cursor: not-allowed;
        }
        .status {
            text-align: center;
            margin-bottom: 20px;
            padding: 10px;
            border-radius: 4px;
        }
        .status.running {
            background-color: #ff9800;
            color: #000;
        }
        .status.idle {
            background-color: #4CAF50;
            color: #fff;
        }
        .terminal-container {
            background-color: #000000;
            padding: 10px;
            border-radius: 4px;
            border: 2px solid #333;
        }
        .connection-status {
            position: fixed;
            top: 10px;
            right: 10px;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
        }
        .connected {
            background-color: #4CAF50;
            color: white;
        }
        .disconnected {
            background-color: #f44336;
            color: white;
        }
        .info {
            background-color: #2196F3;
            color: white;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="connection-status" id="connectionStatus">Connecting...</div>
    
    <div class="container">
        <h1>Shared Terminal - foobar.sh Runner</h1>
        
        <div class="info">
            <strong>Full Terminal Emulation:</strong> This terminal properly handles ANSI colors, cursor movements, 
            and complex terminal applications like vim, tmux, etc. Everyone sees the same terminal state in real-time.
        </div>
        
        <div class="controls">
            <button id="runBtn" class="btn btn-primary">Run foobar.sh</button>
            <button id="clearBtn" class="btn btn-secondary">Clear Terminal</button>
        </div>
        
        <div id="status" class="status idle">Ready to run</div>
        
        <div class="terminal-container">
            <div id="terminal"></div>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xterm/4.19.0/xterm.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xterm/4.19.0/addons/fit/fit.min.js"></script>
    <script>
        // Initialize xterm.js terminal
        const terminal = new Terminal({
            cursorBlink: true,
            theme: {
                background: '#000000',
                foreground: '#ffffff',
                cursor: '#ffffff',
                selection: '#ffffff40',
                black: '#000000',
                red: '#ff5555',
                green: '#50fa7b',
                yellow: '#f1fa8c',
                blue: '#bd93f9',
                magenta: '#ff79c6',
                cyan: '#8be9fd',
                white: '#bfbfbf',
                brightBlack: '#4d4d4d',
                brightRed: '#ff6e67',
                brightGreen: '#5af78e',
                brightYellow: '#f4f99d',
                brightBlue: '#caa9fa',
                brightMagenta: '#ff92d0',
                brightCyan: '#9aedfe',
                brightWhite: '#e6e6e6'
            },
            fontFamily: 'Consolas, "Liberation Mono", Menlo, Courier, monospace',
            fontSize: 14,
            rows: 30,
            cols: 120,
            scrollback: 10000
        });

        // Fit addon for responsive terminal sizing
        const fitAddon = new FitAddon.FitAddon();
        terminal.loadAddon(fitAddon);
        
        // Open terminal in the container
        terminal.open(document.getElementById('terminal'));
        fitAddon.fit();

        // Socket.IO setup
        const socket = io();
        const runBtn = document.getElementById('runBtn');
        const clearBtn = document.getElementById('clearBtn');
        const status = document.getElementById('status');
        const connectionStatus = document.getElementById('connectionStatus');

        // Initial welcome message
        terminal.writeln('\x1b[32mShared Terminal Ready\x1b[0m');
        terminal.writeln('Click "Run foobar.sh" to start the script.');
        terminal.writeln('This terminal supports full ANSI colors and terminal applications.');
        terminal.writeln('');

        // Resize terminal when window resizes
        window.addEventListener('resize', () => {
            fitAddon.fit();
        });

        // Connection status
        socket.on('connect', function() {
            connectionStatus.textContent = 'Connected';
            connectionStatus.className = 'connection-status connected';
            socket.emit('request_state');
        });

        socket.on('disconnect', function() {
            connectionStatus.textContent = 'Disconnected';
            connectionStatus.className = 'connection-status disconnected';
        });

        // Button handlers
        runBtn.addEventListener('click', function() {
            socket.emit('run_script');
        });

        clearBtn.addEventListener('click', function() {
            socket.emit('clear_terminal');
        });

        // Socket event handlers
        socket.on('script_started', function() {
            runBtn.disabled = true;
            runBtn.textContent = 'Running...';
            status.className = 'status running';
            status.textContent = 'Script is running...';
        });

        socket.on('script_finished', function() {
            runBtn.disabled = false;
            runBtn.textContent = 'Run foobar.sh';
            status.className = 'status idle';
            status.textContent = 'Ready to run';
        });

        socket.on('terminal_data', function(data) {
            // Decode base64 data and write to terminal
            const binaryString = atob(data.data);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            terminal.write(bytes);
        });

        socket.on('terminal_cleared', function() {
            terminal.clear();
            terminal.writeln('\x1b[32mTerminal cleared.\x1b[0m');
            terminal.writeln('');
        });

        socket.on('full_terminal_data', function(data) {
            terminal.clear();
            if (data.data) {
                const binaryString = atob(data.data);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                terminal.write(bytes);
            } else {
                terminal.writeln('\x1b[32mShared Terminal Ready\x1b[0m');
                terminal.writeln('Click "Run foobar.sh" to start the script.');
                terminal.writeln('');
            }
        });

        socket.on('button_state', function(data) {
            runBtn.disabled = data.disabled;
            if (data.disabled) {
                runBtn.textContent = 'Running...';
                status.className = 'status running';
                status.textContent = 'Script is running...';
            } else {
                runBtn.textContent = 'Run foobar.sh';
                status.className = 'status idle';
                status.textContent = 'Ready to run';
            }
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    # Send current button state
    emit('button_state', {'disabled': terminal_state.is_running})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")

@socketio.on('request_state')
def handle_request_state():
    # Send current terminal data to newly connected client
    terminal_data = terminal_state.get_terminal_data()
    emit('full_terminal_data', {'data': terminal_data})
    emit('button_state', {'disabled': terminal_state.is_running})

@socketio.on('run_script')
def handle_run_script():
    if terminal_state.is_running:
        # Send error message through terminal
        error_msg = '\r\n\x1b[31mScript is already running!\x1b[0m\r\n'
        error_data = base64.b64encode(error_msg.encode()).decode('ascii')
        emit('terminal_data', {'data': error_data})
        return
    
    # Start the script in a new thread
    thread = threading.Thread(target=run_script_thread)
    thread.daemon = True
    thread.start()

@socketio.on('clear_terminal')
def handle_clear_terminal():
    terminal_state.clear_data()
    socketio.emit('terminal_cleared')

def run_script_thread():
    """Run the foobar.sh script in a separate thread with full PTY support."""
    
    terminal_state.is_running = True
    socketio.emit('script_started')
    
    try:
        # Create a pseudo-terminal for proper ANSI handling
        master_fd, slave_fd = pty.openpty()
        terminal_state.master_fd = master_fd
        
        # Set terminal size (important for applications like vim, tmux)
        os.system(f'stty -F {os.ttyname(slave_fd)} rows 30 cols 120')
        
        script_path = "./foobar.sh"
        
        # Check if script exists
        if not os.path.exists(script_path):
            start_msg = '\r\n\x1b[33mfoobar.sh not found. Creating sample script...\x1b[0m\r\n'
            terminal_state.add_data(start_msg.encode())
            socketio.emit('terminal_data', {
                'data': base64.b64encode(start_msg.encode()).decode('ascii')
            })
            
            # Create a sample script for demonstration
            create_sample_script()
            
        # Start message
        start_msg = f'\r\n\x1b[32m=== Starting {script_path} ===\x1b[0m\r\n'
        terminal_state.add_data(start_msg.encode())
        socketio.emit('terminal_data', {
            'data': base64.b64encode(start_msg.encode()).decode('ascii')
        })
        
        # Set environment variables for proper terminal behavior
        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        env['COLUMNS'] = '120'
        env['LINES'] = '30'
        
        # Run the script
        process = subprocess.Popen(
            ["/bin/bash", script_path],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            preexec_fn=os.setsid
        )
        
        terminal_state.process = process
        
        # Close slave fd in parent process
        os.close(slave_fd)
        
        # Read output from master fd and broadcast to all clients
        while process.poll() is None:
            try:
                # Use select to check if data is available
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(master_fd, 4096)  # Read larger chunks
                        if data:
                            # Store raw data
                            terminal_state.add_data(data)
                            # Send to all connected clients
                            socketio.emit('terminal_data', {
                                'data': base64.b64encode(data).decode('ascii')
                            })
                    except OSError:
                        break
            except select.error:
                break
        
        # Wait for process to complete
        return_code = process.wait()
        
        # Read any remaining output
        try:
            remaining_data = os.read(master_fd, 4096)
            if remaining_data:
                terminal_state.add_data(remaining_data)
                socketio.emit('terminal_data', {
                    'data': base64.b64encode(remaining_data).decode('ascii')
                })
        except OSError:
            pass
        
        # Emit completion message
        completion_msg = f'\r\n\x1b[32m=== Script completed with return code: {return_code} ===\x1b[0m\r\n'
        terminal_state.add_data(completion_msg.encode())
        socketio.emit('terminal_data', {
            'data': base64.b64encode(completion_msg.encode()).decode('ascii')
        })
        
    except Exception as e:
        error_msg = f'\r\n\x1b[31mError running script: {str(e)}\x1b[0m\r\n'
        terminal_state.add_data(error_msg.encode())
        socketio.emit('terminal_data', {
            'data': base64.b64encode(error_msg.encode()).decode('ascii')
        })
    
    finally:
        # Cleanup
        if terminal_state.master_fd:
            try:
                os.close(terminal_state.master_fd)
            except OSError:
                pass
        
        terminal_state.is_running = False
        terminal_state.process = None
        terminal_state.master_fd = None
        socketio.emit('script_finished')

def create_sample_script():
    """Create a sample foobar.sh script with rich terminal features."""
    script_content = '''#!/bin/bash

# Enhanced demo script with colors and terminal features
echo -e "\\033[1;34mStarting foobar.sh demo script...\\033[0m"
echo -e "This script demonstrates \\033[1;33mfull terminal emulation\\033[0m capabilities."
echo ""

# Test basic colors
echo -e "\\033[31mRed text\\033[0m"
echo -e "\\033[32mGreen text\\033[0m" 
echo -e "\\033[33mYellow text\\033[0m"
echo -e "\\033[34mBlue text\\033[0m"
echo -e "\\033[35mMagenta text\\033[0m"
echo -e "\\033[36mCyan text\\033[0m"
echo ""

# Test bold and styling
echo -e "\\033[1mBold text\\033[0m"
echo -e "\\033[4mUnderlined text\\033[0m"
echo -e "\\033[7mReversed text\\033[0m"
echo ""

# Simulate progress with colors
echo -e "\\033[1;36mProgress simulation:\\033[0m"
for i in {1..10}; do
    echo -ne "\\033[33mProcessing step $i/10...\\033[0m"
    sleep 0.5
    echo -e " \\033[1;32m✓ Complete\\033[0m"
done

echo ""
echo -e "\\033[1;35mTesting cursor movements and clearing...\\033[0m"

# Test some cursor movements
echo -ne "This text will be overwritten..."
sleep 1
echo -ne "\\r\\033[KNew text on the same line!"
sleep 1
echo ""

# Test background colors
echo -e "\\033[41mRed background\\033[0m"
echo -e "\\033[42mGreen background\\033[0m"
echo -e "\\033[43mYellow background\\033[0m"
echo ""

# Simulate some "errors" and warnings with colors
echo -e "\\033[1;31mERROR: This is a sample error message\\033[0m" >&2
echo -e "\\033[1;33mWARNING: This is a sample warning message\\033[0m" >&2
echo -e "\\033[1;36mINFO: This is an informational message\\033[0m"

echo ""
echo -e "\\033[1;32mfoobar.sh completed successfully!\\033[0m"
echo -e "\\033[2;37m(This terminal now supports vim, tmux, and other complex applications)\\033[0m"
'''
    
    with open('./foobar.sh', 'w') as f:
        f.write(script_content)
    
    # Make it executable
    os.chmod('./foobar.sh', 0o755)
    
    msg = '\x1b[32mCreated enhanced sample foobar.sh script.\x1b[0m\r\n'
    terminal_state.add_data(msg.encode())
    socketio.emit('terminal_data', {
        'data': base64.b64encode(msg.encode()).decode('ascii')
    })

def signal_handler(sig, frame):
    """Handle shutdown gracefully."""
    print("\nShutting down gracefully...")
    if terminal_state.process:
        try:
            os.killpg(os.getpgid(terminal_state.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    sys.exit(0)

if __name__ == '__main__':
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Starting Shared Terminal Web Service with Full Terminal Emulation...")
    print("Open your browser to http://localhost:5100")
    print("Press Ctrl+C to stop the server")
    
    # Run the Flask-SocketIO app
    socketio.run(app, host='0.0.0.0', port=5100, debug=False)
