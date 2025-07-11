#!/usr/bin/env python3
"""
Shared Terminal Web Service with Full Terminal Emulation
A service that provides a shared terminal interface with proper ANSI handling.
"""

import argparse
import os
import pty
import select
import subprocess
import threading
import time
import base64
from datetime import datetime
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import signal
import sys

app = Flask(__name__, static_folder='static', static_url_path='/static')
socketio = SocketIO(app, cors_allowed_origins="*")

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
SCRIPT_PATH = None
RUN_ON_PAGE_LOAD = False

@app.route('/')
def index():
    if RUN_ON_PAGE_LOAD and not terminal_state.is_running:
        thread = threading.Thread(target=run_script_thread)
        thread.daemon = True
        thread.start()
    return render_template("index.html")

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
    """Run the script in a separate thread with full PTY support."""
    
    terminal_state.is_running = True
    socketio.emit('script_started')
    
    try:
        # Create a pseudo-terminal for proper ANSI handling
        master_fd, slave_fd = pty.openpty()
        terminal_state.master_fd = master_fd
        
        # Set terminal size (important for applications like vim, tmux)
        os.system(f'stty -F {os.ttyname(slave_fd)} rows 30 cols 120')
        
        script_path = SCRIPT_PATH
            
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
    parser = argparse.ArgumentParser(description="Shared Terminal Web Service Daemon")
    parser.add_argument("script", help="Script to run (e.g. foobar.sh)")
    parser.add_argument("--port", type=int, default=5100, help="Port to run the server on (default: 5100)")
    parser.add_argument("--run-on-page-load", action="store_true", help="If set, the script will run automatically when a page is loaded")
    args = parser.parse_args()
    SCRIPT_PATH = args.script
    RUN_ON_PAGE_LOAD = args.run_on_page_load

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Sharing script {}".format(SCRIPT_PATH))
    print("Press Ctrl+C to stop the server")
    
    # Run the Flask-SocketIO app with the specified port
    socketio.run(app, host='0.0.0.0', port=args.port, debug=False)
