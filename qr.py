#!/usr/bin/env python3
"""
qrtunnel: Simple file sharing via QR code.
Usage: qrtunnel <file_path1> [<file_path2> ...]
"""

import os
import sys
import random
import socket
import subprocess
import threading
import time
import re
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from pathlib import Path
import termios
import tty


def getch():
    """Reads a single character from stdin without echoing or requiring Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch


class Config:
    """Configuration constants"""
    LOCAL_PORT = 8000
    REMOTE_PORT = 80
    SSH_HOST = "nokey@localhost.run"
    

class FileShareHandler(BaseHTTPRequestHandler):
    """HTTP request handler for file sharing"""
    
    # Class variables shared across instances
    file_paths = None
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/download':
            self.serve_files_as_zip()
        else:
            self.send_download_page()
    
    def send_download_page(self):
        """Send HTML page with a download button"""
        file_list_html = "".join(f"<li>{os.path.basename(p)}</li>" for p in self.file_paths)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>qrtunnel - File Download</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: white;
        }}
        .container {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        h1 {{
            margin-bottom: 20px;
            font-size: 32px;
            font-weight: 600;
        }}
        p {{
            margin-bottom: 30px;
            font-size: 16px;
            opacity: 0.8;
        }}
        .file-list {{
            list-style: none;
            margin-bottom: 40px;
            text-align: left;
            background: rgba(0,0,0,0.2);
            padding: 20px;
            border-radius: 10px;
        }}
        .file-list li {{
            padding: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .file-list li:last-child {{
            border-bottom: none;
        }}
        .download-button {{
            display: inline-block;
            padding: 20px 40px;
            background: #ff6b6b;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: transform 0.2s, background 0.2s;
        }}
        .download-button:hover {{
            transform: translateY(-3px);
            background: #ff8787;
        }}
        .download-button:active {{
            transform: translateY(0);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚀 Files Ready for Download</h1>
        <p>Click the button below to download all files as a single ZIP archive.</p>
        <ul class="file-list">
            {file_list_html}
        </ul>
        <a href="/download" class="download-button">Download All Files</a>
    </div>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Content-Length', len(html.encode()))
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_files_as_zip(self):
        """Create a ZIP archive of all files and serve it"""
        try:
            import zipfile
            from io import BytesIO

            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in self.file_paths:
                    zipf.write(file_path, os.path.basename(file_path))
            
            zip_buffer.seek(0)
            zip_data = zip_buffer.getvalue()

            self.send_response(200)
            self.send_header('Content-type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="files.zip"')
            self.send_header('Content-Length', len(zip_data))
            self.end_headers()
            self.wfile.write(zip_data)
            
            print(f"✓ Files served as ZIP to {self.client_address[0]}")
        except Exception as e:
            print(f"✗ Error creating or serving ZIP file: {e}")
            self.send_error(500, "Internal server error")


class SSHTunnel:
    """Manages SSH reverse tunnel to serveo.net"""
    
    def __init__(self, local_port, remote_port):
        self.local_port = local_port
        self.remote_port = remote_port
        self.process = None
        self.public_url = None
        
    def start(self):
        """Start the SSH tunnel and extract the public URL"""
        print(f"\n[*] Starting SSH tunnel to {Config.SSH_HOST}...")
        
        # Build SSH command
        cmd = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ServerAliveInterval=60',
            '-R', f'{self.remote_port}:localhost:{self.local_port}',
            Config.SSH_HOST
        ]
        
        # Start SSH process
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True
        )
        
        # Wait for URL in stdout
        print("[*] Waiting for public URL...")
        url_pattern = re.compile(r'https://[a-zA-Z0-9.-]+')
        
        for _ in range(30):  # Wait up to 30 seconds
            line = self.process.stdout.readline()
            if line:
                print(f"[SSH] {line.strip()}")
                match = url_pattern.search(line)
                if match:
                    self.public_url = match.group(0)
                    print(f"✓ Tunnel established: {self.public_url}")
                    return True
            time.sleep(1)
        
        print("✗ Failed to get public URL from SSH tunnel")
        return False
    
    def stop(self):
        """Stop the SSH tunnel"""
        if self.process:
            self.process.terminate()
            self.process.wait()
            print("\n[*] SSH tunnel closed")


def generate_qr_code(url):
    """Generate and display QR code in terminal"""
    try:
        import qrcode
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        print("\n" + "="*60)
        print("SCAN THIS QR CODE TO ACCESS THE FILES:")
        print("="*60)
        qr.print_ascii(invert=True)
        print("="*60)
        print(f"\n🌐 URL: {url}")
        print("="*60 + "\n")
        
    except ImportError:
        # Fallback if qrcode is not installed
        print("\n" + "="*60)
        print("⚠️  QR code library not installed")
        print("Install with: pip install qrcode")
        print("="*60)
        print(f"\n🌐 URL: {url}")
        print("="*60 + "\n")


def check_dependencies():
    """Check if required dependencies are available"""
    # Check if SSH is available
    try:
        subprocess.run(['ssh', '-V'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("✗ Error: SSH is not installed or not in PATH")
        sys.exit(1)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="qrtunnel: Simple file sharing via QR code.",
        usage="qrtunnel <file_path1> [<file_path2> ...]"
    )
    parser.add_argument('file_paths', nargs='+', help='One or more paths to the files you want to share.')
    
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    file_paths = args.file_paths
    
    # Validate files
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"✗ Error: File '{file_path}' not found")
            sys.exit(1)
        
        if not os.path.isfile(file_path):
            print(f"✗ Error: '{file_path}' is not a file")
            sys.exit(1)
    
    # Check dependencies
    check_dependencies()
    
    # Display banner
    print("\n" + "="*60)
    print("qrtunnel - Simple File Sharing")
    print("="*60)
    print("Files to be shared:")
    for file_path in file_paths:
        print(f"  - {os.path.basename(file_path)} ({os.path.getsize(file_path)} bytes)")
    print("="*60 + "\n")
    
    # Set up handler with file paths
    FileShareHandler.file_paths = file_paths
    
    # Start HTTP server in a separate thread
    server = HTTPServer(('localhost', Config.LOCAL_PORT), FileShareHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"[*] HTTP server started on localhost:{Config.LOCAL_PORT}")
    
    # Start SSH tunnel
    tunnel = SSHTunnel(Config.LOCAL_PORT, Config.REMOTE_PORT)
    
    if not tunnel.start():
        print("✗ Failed to establish SSH tunnel")
        server.shutdown()
        sys.exit(1)
    
    # Generate and display QR code
    generate_qr_code(tunnel.public_url)
    
    print("[*] Server is running. Press 'q' to quit, or Ctrl+C to stop.\n")
    
    try:
        # Keep the main thread alive, checking for 'q' to quit
        while True:
            char = getch()
            if char == 'q':
                print("\n\n[*] 'q' pressed. Shutting down...")
                break
            time.sleep(0.1) # Small delay to prevent busy-waiting
    except KeyboardInterrupt:
        print("\n\n[*] Ctrl+C pressed. Shutting down...")
    finally:
        tunnel.stop()
        server.shutdown()
        print("[*] Server stopped. Goodbye!")

if __name__ == '__main__':
    main()
