#!/usr/bin/env python3
"""
shareqr: Simple file sharing via QR code.
Usage: shareqr <file_path1> [<file_path2> ...]
"""

import os
import sys
import socket
import subprocess
import threading
import time
import re
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path


def getch():
    """Reads a single character from stdin without echoing or requiring Enter."""
    if os.name == 'nt':  # Windows
        try:
            import msvcrt
            return msvcrt.getch().decode('utf-8', errors='ignore')
        except Exception:
            return None
    else:  # Unix-like systems (Linux, macOS)
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return ch
        except Exception:
            return None


def find_free_port():
    """Find a free port on localhost"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


class Config:
    """Configuration constants"""
    LOCAL_PORT = None  # Will be set dynamically
    REMOTE_PORT = 80
    SSH_HOST = "nokey@localhost.run"


class FileShareHandler(BaseHTTPRequestHandler):
    """HTTP request handler for file sharing"""

    # Class variables shared across instances
    file_paths = None

    def log_message(self, format, *args):
        """Override to add custom logging"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {self.client_address[0]} - {format % args}")
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)

        if parsed_path.path == '/download':
            self.serve_files_as_zip()
        elif parsed_path.path == '/health':
            self.send_health_check()
        else:
            self.send_download_page()
    
    def send_health_check(self):
        """Send health check response"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')

    def send_download_page(self):
        """Send HTML page with a download button"""
        try:
            file_list_html = "".join(
                f"<li><span class='icon'>📄</span> {os.path.basename(p)}</li>" 
                for p in self.file_paths
            )

            html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>shareqr - File Download</title>
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
            max-height: 300px;
            overflow-y: auto;
        }}
        .file-list li {{
            padding: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .file-list li:last-child {{
            border-bottom: none;
        }}
        .icon {{
            font-size: 18px;
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
            box-shadow: 0 4px 15px rgba(255, 107, 107, 0.4);
        }}
        .download-button:hover {{
            transform: translateY(-3px);
            background: #ff8787;
        }}
        .download-button:active {{
            transform: translateY(0);
        }}
        .footer {{
            margin-top: 25px;
            font-size: 13px;
            opacity: 0.6;
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
        <a href="/download" class="download-button">📥 Download All Files</a>
        <div class="footer">
            <p>Powered by shareqr</p>
        </div>
    </div>
</body>
</html>"""

            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(html.encode('utf-8')))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        except Exception as e:
            print(f"✗ Error sending download page: {e}")
            self.send_error(500, "Internal server error")

    def serve_files_as_zip(self):
        """Create a ZIP archive of all files and serve it"""
        try:
            import zipfile
            from io import BytesIO

            print(f"[*] Creating ZIP archive for {self.client_address[0]}")

            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in self.file_paths:
                    try:
                        zipf.write(file_path, os.path.basename(file_path))
                    except Exception as e:
                        print(f"✗ Failed to add {file_path} to ZIP: {e}")

            zip_buffer.seek(0)
            zip_data = zip_buffer.getvalue()

            self.send_response(200)
            self.send_header('Content-type', 'application/zip')
            self.send_header('Content-Disposition', 'attachment; filename="shareqr_files.zip"')
            self.send_header('Content-Length', len(zip_data))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(zip_data)

            print(f"✓ Files served as ZIP ({len(zip_data)} bytes) to {self.client_address[0]}")
        except Exception as e:
            print(f"✗ Error creating or serving ZIP file: {e}")
            self.send_error(500, "Internal server error")


class SSHTunnel:
    """Manages SSH reverse tunnel to localhost.run"""

    def __init__(self, local_port, remote_port):
        self.local_port = local_port
        self.remote_port = remote_port
        self.process = None
        self.public_url = None
        self.running = False
        self.output_thread = None

    def _read_output(self):
        """Read output from SSH process, extracting URL and discarding other output."""
        url_pattern = re.compile(r'https://[a-zA-Z0-9.-]+')
        
        try:
            while self.running and self.process:
                # Read from both stdout and stderr
                line = None
                if self.process.stdout:
                    line = self.process.stdout.readline()
                
                if not line and self.process.stderr:
                    line = self.process.stderr.readline()
                
                if line:
                    line = line.strip()
                    
                    # Skip empty lines
                    if not line:
                        continue
                    
                    if not self.public_url:
                        match = url_pattern.search(line)
                        if match:
                            self.public_url = match.group(0)
                            print(f"✓ Public URL obtained: {self.public_url}")
                
                # Check if the process has terminated
                if self.process.poll() is not None:
                    break
                    
                time.sleep(0.05) # Shorter sleep to consume output faster
        except Exception as e:
            # Only print error if URL was not found, to avoid cluttering output
            if not self.public_url:
                print(f"[SSH] Error reading output: {e}")

    def start(self):
        """Start the SSH tunnel and extract the public URL"""
        print(f"\n[*] Starting SSH tunnel to {Config.SSH_HOST}...")

        # Build SSH command with cross-platform compatible options
        cmd = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=' + (os.devnull if os.name != 'nt' else 'NUL'),
            '-o', 'ServerAliveInterval=60',
            '-o', 'ServerAliveCountMax=3',
            '-R', f'{self.remote_port}:localhost:{self.local_port}',
            Config.SSH_HOST
        ]

        try:
            # Start SSH process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )

            self.running = True

            # Start output reading thread
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()

            # Wait for URL with timeout
            print("[*] Waiting for public URL (this may take 20-30 seconds)...")
            start_time = time.time()
            timeout = 35
            
            while time.time() - start_time < timeout:
                if self.public_url:
                    print("✓ SSH tunnel established successfully!")
                    return True
                
                if self.process.poll() is not None:
                    print("✗ SSH process terminated unexpectedly")
                    return False
                
                time.sleep(0.5)

            print("✗ Timeout waiting for public URL from SSH tunnel")
            return False

        except FileNotFoundError:
            print("✗ SSH command not found. Please ensure SSH is installed and in PATH")
            print("\nInstallation instructions:")
            print("  Windows: Settings > Apps > Optional Features > Add OpenSSH Client")
            print("  macOS: SSH is pre-installed")
            print("  Linux: sudo apt-get install openssh-client")
            return False
        except Exception as e:
            print(f"✗ Failed to start SSH tunnel: {e}")
            return False

    def stop(self):
        """Stop the SSH tunnel"""
        self.running = False
        
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[*] Forcefully killing SSH process...")
                self.process.kill()
                self.process.wait()
            except Exception as e:
                print(f"✗ Error stopping SSH tunnel: {e}")
            
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
        print("Install with: pip install qrcode[pil]")
        print("="*60)
        print(f"\n🌐 URL: {url}")
        print("="*60 + "\n")
    except Exception as e:
        print(f"[*] QR code generation failed: {e}")
        print("\n" + "="*60)
        print(f"🌐 URL: {url}")
        print("="*60 + "\n")


def check_dependencies():
    """Check if required dependencies are available"""
    # Check if SSH is available
    try:
        result = subprocess.run(
            ['ssh', '-V'],
            capture_output=True,
            timeout=5
        )
        print("[*] ✓ SSH is available")
        return True
    except FileNotFoundError:
        print("✗ SSH is not installed or not in PATH")
        print("\nInstallation instructions:")
        print("  Windows: Settings > Apps > Optional Features > Add OpenSSH Client")
        print("  macOS: SSH is pre-installed")
        print("  Linux: sudo apt-get install openssh-client")
        return False
    except subprocess.TimeoutExpired:
        print("✗ SSH command timed out")
        return False
    except Exception as e:
        print(f"✗ Error checking SSH: {e}")
        return False


def format_size(size_bytes):
    """Format bytes to human-readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="shareqr: Simple file sharing via QR code.",
        usage="shareqr <file_path1> [<file_path2> ...]"
    )
    parser.add_argument('file_paths', nargs='+', help='One or more paths to the files you want to share.')
    
    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    file_paths = args.file_paths

    # Validate files
    validated_files = []
    total_size = 0
    
    for file_path in file_paths:
        path = Path(file_path)
        
        if not path.exists():
            print(f"✗ Error: File '{file_path}' not found")
            sys.exit(1)

        if not path.is_file():
            print(f"✗ Error: '{file_path}' is not a file")
            sys.exit(1)
        
        validated_files.append(str(path.absolute()))
        total_size += path.stat().st_size

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Display banner
    print("\n" + "="*60)
    print("shareqr - Simple File Sharing")
    print("="*60)
    print("Files to be shared:")
    for file_path in validated_files:
        size = os.path.getsize(file_path)
        print(f"  - {os.path.basename(file_path)} ({format_size(size)})")
    print(f"\nTotal size: {format_size(total_size)}")
    print("="*60 + "\n")

    # Find free port
    Config.LOCAL_PORT = find_free_port()
    print(f"[*] Using local port: {Config.LOCAL_PORT}")

    # Set up handler with file paths
    FileShareHandler.file_paths = validated_files

    # Start HTTP server in a separate thread
    try:
        server = HTTPServer(('localhost', Config.LOCAL_PORT), FileShareHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        print(f"[*] ✓ HTTP server started on localhost:{Config.LOCAL_PORT}")
    except Exception as e:
        print(f"✗ Failed to start HTTP server: {e}")
        sys.exit(1)

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
            if char and char.lower() == 'q':
                print("\n\n[*] 'q' pressed. Shutting down...")
                break
            time.sleep(0.1)  # Small delay to prevent busy-waiting
    except KeyboardInterrupt:
        print("\n\n[*] Ctrl+C pressed. Shutting down...")
    finally:
        tunnel.stop()
        server.shutdown()
        print("[*] Server stopped. Goodbye!")


if __name__ == '__main__':
    main()
