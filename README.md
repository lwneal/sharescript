# Shared Script Runner

You have a shell script `foobar.sh`. Someone in the office has to run this script sometimes. You want everyone to see when the script last ran, whether it is still running right now, and whether it crashed.

Use `python3 sharescript.py foobar.sh` and tell everyone to open a browser to `http://127.0.0.1:5100`

Now everyone can see the script, whether it ran, and what its output was. Anyone can run the script. But only one copy can run at a time.


## Features

- **Full Terminal Emulation:** Displays output with proper ANSI support.
- **Live Monitoring:** Everyone viewing gets a live stream of the script's output.
- **Secure:** No options or parameters of any kind: it just runs the script.

## Setup

Ensure you have Python 3 installed. Install necessary packages using pip:

```bash
pip install Flask Flask-SocketIO
```

## Usage

Run the script with the required and optional arguments:

```bash
python3 sharescript.py <script-to-run> [options]
```

### Positional Argument

- `<script-to-run>`: The shell script to run (e.g. `foobar.sh`).

### Options

- `--port`: Port to run the server on (default: 5100).
- `--run-on-page-load`: If specified, the script runs automatically when the UI page loads.
- `--header`: Custom header text to display on the UI (default: "Job Runner").
- `--title`: Custom title text to display in the browser title bar. If not provided, defaults to "Shared Terminal - [scriptname] Runner".

### Example

Run a script with a custom header and title:

```bash
python3 sharescript.py foobar.sh --port 5100 --header "Office Terminal" --title "Office Job Runner" --run-on-page-load
```

## Viewing the UI

After starting the server, open your browser and navigate to:

```
http://<local_ip>:<port>
```

Replace `<local_ip>` with the IP of the machine running the script. Replace <port> with chosen port (default is 5100).
