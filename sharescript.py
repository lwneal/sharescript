#!/usr/bin/env python3
"""
Shared Terminal Web Service
A simple HTTP service that provides a shared terminal interface for running scripts.
"""

import os
import pty
import select
import subprocess
import threading
import time
from datetime import datetime
from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit, request as socketio_request
import signal
import sys

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
class TerminalState:
    def __init__(self):
        self.is_running = False
        self.output_buffer = []
        self.process = None
        self.master_fd = None
        self.lock = threading.Lock()
        
    def add_output(self, data):
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.output_buffer.append({
                'timestamp': timestamp,
                'data': data
            })
            # Keep only last 10000 lines to prevent memory issues
            if len(self.output_buffer) > 10000:
                self.output_buffer = self.output_buffer[-10000:]
    
    def get_full_output(self):
        with self.lock:
            return self.output_buffer.copy()
    
    def clear_output(self):
        with self.lock:
            self.output_buffer.clear()

terminal_state = TerminalState()

# HTML template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Shared Terminal - foobar.sh Runner</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: 'Courier New', monospace;
            margin: 0;
            padding: 20px;
            background-color: #1e1e1e;
            color: #ffffff;
        }
        .container {
            max-width: 1200px;
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
        .terminal {
            background-color: #000000;
            color: #00ff00;
            padding: 20px;
            border-radius: 4px;
            height: 600px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            border: 2px solid #333;
        }
        .terminal-line {
            margin: 0;
            line-height: 1.2;
        }
        .timestamp {
            color: #888;
            margin-right: 10px;
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
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
</head>
<body>
    <div class="connection-status" id="connectionStatus">Connecting...</div>
    
    <div class="container">
        <h1>Shared Terminal - foobar.sh Runner</h1>
        
        <div class="controls">
            <button id="runBtn" class="btn btn-primary">Run foobar.sh</button>
            <button id="clearBtn" class="btn btn-secondary">Clear Terminal</button>
        </div>
        
        <div id="status" class="status idle">Ready to run</div>
        
        <div id="terminal" class="terminal">
            <div class="terminal-line">Shared terminal ready. Click "Run foobar.sh" to start the script.</div>
            <div class="terminal-line">Anyone can view this terminal, even if they join while the script is running.</div>
        </div>
    </div>

    <script>
        const socket = io();
        const terminal = document.getElementById('terminal');
        const runBtn = document.getElementById('runBtn');
        const clearBtn = document.getElementById('clearBtn');
        const status = document.getElementById('status');
        const connectionStatus = document.getElementById('connectionStatus');

        // Connection status
        socket.on('connect', function() {
            connectionStatus.textContent = 'Connected';
            connectionStatus.className = 'connection-status connected';
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

        socket.on('terminal_output', function(data) {
            const line = document.createElement('div');
            line.className = 'terminal-line';
            
            const timestamp = document.createElement('span');
            timestamp.className = 'timestamp';
            timestamp.textContent = data.timestamp;
            
            const content = document.createElement('span');
            content.innerHTML = escapeHtml(data.data);
            
            line.appendChild(timestamp);
            line.appendChild(content);
            terminal.appendChild(line);
            
            // Auto-scroll to bottom
            terminal.scrollTop = terminal.scrollHeight;
        });

        socket.on('terminal_cleared', function() {
            terminal.innerHTML = '<div class="terminal-line">Terminal cleared.</div>';
        });

        socket.on('full_output', function(data) {
            terminal.innerHTML = '';
            data.forEach(function(item) {
                const line = document.createElement('div');
                line.className = 'terminal-line';
                
                const timestamp = document.createElement('span');
                timestamp.className = 'timestamp';
                timestamp.textContent = item.timestamp;
                
                const content = document.createElement('span');
                content.innerHTML = escapeHtml(item.data);
                
                line.appendChild(timestamp);
                line.appendChild(content);
                terminal.appendChild(line);
            });
            terminal.scrollTop = terminal.scrollHeight;
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

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Request current state when connecting
        socket.on('connect', function() {
            socket.emit('request_state');
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
    print(f"Client connected: {socketio_request.sid}")
    # Send current button state
    emit('button_state', {'disabled': terminal_state.is_running})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {socketio_request.sid}")

@socketio.on('request_state')
def handle_request_state():
    # Send current output buffer to newly connected client
    output = terminal_state.get_full_output()
    emit('full_output', output)
    emit('button_state', {'disabled': terminal_state.is_running})

@socketio.on('run_script')
def handle_run_script():
    if terminal_state.is_running:
        emit('terminal_output', {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'data': 'Script is already running!'
        })
        return
    
    # Start the script in a new thread
    thread = threading.Thread(target=run_script_thread)
    thread.daemon = True
    thread.start()

@socketio.on('clear_terminal')
def handle_clear_terminal():
    terminal_state.clear_output()
    socketio.emit('terminal_cleared')

def run_script_thread():
    """Run the foobar.sh script in a separate thread with PTY for proper terminal handling."""
    
    terminal_state.is_running = True
    socketio.emit('script_started')
    
    try:
        # Create a pseudo-terminal for proper ANSI handling
        master_fd, slave_fd = pty.openpty()
        terminal_state.master_fd = master_fd
        
        # Start the script
        script_path = "./foobar.sh"
        
        # Check if script exists
        if not os.path.exists(script_path):
            output_msg = f"Error: {script_path} not found. Creating a sample script..."
            terminal_state.add_output(output_msg)
            socketio.emit('terminal_output', {
                'timestamp': datetime.now().strftime("%H:%M:%S"),
                'data': output_msg
            })
            
            # Create a sample script for demonstration
            create_sample_script()
            
        # Run the script
        process = subprocess.Popen(
            ["/bin/bash", script_path],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            universal_newlines=True,
            preexec_fn=os.setsid
        )
        
        terminal_state.process = process
        
        # Close slave fd in parent process
        os.close(slave_fd)
        
        # Read output from master fd
        while process.poll() is None:
            try:
                # Use select to check if data is available
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(master_fd, 1024).decode('utf-8', errors='replace')
                        if data:
                            # Split by lines and emit each line
                            lines = data.splitlines(keepends=True)
                            for line in lines:
                                if line.strip():  # Only emit non-empty lines
                                    terminal_state.add_output(line.rstrip())
                                    socketio.emit('terminal_output', {
                                        'timestamp': datetime.now().strftime("%H:%M:%S"),
                                        'data': line.rstrip()
                                    })
                    except OSError:
                        break
            except select.error:
                break
        
        # Wait for process to complete
        return_code = process.wait()
        
        # Read any remaining output
        try:
            remaining_data = os.read(master_fd, 1024).decode('utf-8', errors='replace')
            if remaining_data:
                lines = remaining_data.splitlines()
                for line in lines:
                    if line.strip():
                        terminal_state.add_output(line)
                        socketio.emit('terminal_output', {
                            'timestamp': datetime.now().strftime("%H:%M:%S"),
                            'data': line
                        })
        except OSError:
            pass
        
        # Emit completion message
        completion_msg = f"Script completed with return code: {return_code}"
        terminal_state.add_output(completion_msg)
        socketio.emit('terminal_output', {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'data': completion_msg
        })
        
    except Exception as e:
        error_msg = f"Error running script: {str(e)}"
        terminal_state.add_output(error_msg)
        socketio.emit('terminal_output', {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'data': error_msg
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
    """Create a sample foobar.sh script for demonstration."""
    script_content = '''#!/bin/bash

echo "Starting foobar.sh demo script..."
echo "This is a sample script that demonstrates terminal output."
echo ""

# Simulate some work with progress
for i in {1..10}; do
    echo "Processing step $i/10..."
    sleep 1
    
    # Show some colored output if supported
    if command -v tput > /dev/null; then
        echo "$(tput setaf 2)✓ Step $i completed$(tput sgr0)"
    else
        echo "✓ Step $i completed"
    fi
done

echo ""
echo "Simulating some errors and warnings..."
echo "WARNING: This is a sample warning message" >&2
echo "INFO: This is an informational message"

echo ""
echo "Final processing..."
sleep 2

echo "foobar.sh completed successfully!"
'''
    
    with open('./foobar.sh', 'w') as f:
        f.write(script_content)
    
    # Make it executable
    os.chmod('./foobar.sh', 0o755)
    
    msg = "Created sample foobar.sh script."
    terminal_state.add_output(msg)
    socketio.emit('terminal_output', {
        'timestamp': datetime.now().strftime("%H:%M:%S"),
        'data': msg
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
    
    print("Starting Shared Terminal Web Service...")
    print("Open your browser to http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    
    # Run the Flask-SocketIO app
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
