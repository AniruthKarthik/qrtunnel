#!/usr/bin/env python3
"""
qrtunnel: Simple cross-platform file sharing via QR code with ngrok authentication.
Usage: qrtunnel <file_path1> [<file_path2> ...]

Dependencies:
    pip install pyngrok qrcode[pil]
"""

import os
import sys
import threading
import time
import argparse
import platform
import subprocess
import re
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path


def getch():
    """Reads a single character from stdin without echoing or requiring Enter."""
    
    if platform.system() == 'Windows':
        try:
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getch().decode('utf-8', errors='ignore')
            return None
        except:
            return None
    else:
        try:
            import select
            import sys
            import tty
            import termios
            
            # Check if there's input available (non-blocking)
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(sys.stdin.fileno())
                    ch = sys.stdin.read(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                return ch
            return None
        except:
            return None


class Config:
    """Configuration constants"""
    LOCAL_PORT = 8000
    CONFIG_DIR = Path.home() / ".qrtunnel"
    CONFIG_FILE = CONFIG_DIR / "config.json"
    

class FileShareHandler(BaseHTTPRequestHandler):
    """HTTP request handler for file sharing"""
    
    file_paths = None
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass
    
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
            background: #1a1a2e;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #eee;
        }}
        .container {{
            background: #16213e;
            border-radius: 8px;
            padding: 40px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            max-width: 480px;
            width: 100%;
        }}
        .header {{
            text-align: center;
            margin-bottom: 32px;
            padding-bottom: 24px;
            border-bottom: 1px solid #2a3a5e;
        }}
        h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #fff;
        }}
        .subtitle {{
            font-size: 14px;
            color: #888;
        }}
        .file-section {{
            margin-bottom: 32px;
        }}
        .file-section-title {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #666;
            margin-bottom: 12px;
        }}
        .file-list {{
            list-style: none;
            background: #0f0f1a;
            border-radius: 6px;
            border: 1px solid #2a3a5e;
        }}
        .file-list li {{
            padding: 12px 16px;
            font-size: 14px;
            font-family: 'SF Mono', 'Consolas', monospace;
            border-bottom: 1px solid #2a3a5e;
            color: #ccc;
        }}
        .file-list li:last-child {{
            border-bottom: none;
        }}
        .download-button {{
            display: block;
            width: 100%;
            padding: 16px 24px;
            background: #4361ee;
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            text-decoration: none;
            text-align: center;
            transition: background 0.2s ease;
        }}
        .download-button:hover {{
            background: #3a56d4;
        }}
        .download-button:active {{
            background: #324bc2;
        }}
        .footer {{
            text-align: center;
            margin-top: 24px;
            font-size: 12px;
            color: #555;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Files Ready</h1>
            <p class="subtitle">Download as ZIP archive</p>
        </div>
        <div class="file-section">
            <p class="file-section-title">Files ({len(self.file_paths)})</p>
            <ul class="file-list">
                {file_list_html}
            </ul>
        </div>
        <a href="/download" class="download-button">Download All</a>
        <p class="footer">qrtunnel</p>
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


class NgrokAuth:
    """Manages ngrok authentication"""
    
    def __init__(self):
        self.config_dir = Config.CONFIG_DIR
        self.config_file = Config.CONFIG_FILE
        
    def ensure_config_dir(self):
        """Create config directory if it doesn't exist"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
    def load_config(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def save_config(self, config):
        """Save configuration to file"""
        self.ensure_config_dir()
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
    
    def get_authtoken(self):
        """Get ngrok authtoken from config"""
        config = self.load_config()
        return config.get('ngrok_authtoken')
    
    def save_authtoken(self, token):
        """Save ngrok authtoken to config"""
        config = self.load_config()
        config['ngrok_authtoken'] = token
        self.save_config(config)
    
    def setup_ngrok_account(self):
        """Interactive setup for ngrok account"""
        print("\n" + "="*60)
        print("NGROK ACCOUNT SETUP")
        print("="*60)
        print("\nNgrok is a reliable tunneling service that works on all platforms.")
        print("\n🔑 To get your ngrok authtoken:")
        print("   1. Visit: https://dashboard.ngrok.com/signup")
        print("   2. Sign up for a FREE account (email required)")
        print("   3. Copy your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken")
        
        # Show no-auth alternative on Mac/Linux
        if platform.system() != 'Windows':
            print("\n" + "-"*60)
            print("💡 ALTERNATIVE: No Sign-up Required!")
            print("-"*60)
            print("If you don't want to sign up for ngrok, you can use the")
            print("--noauth flag which uses SSH tunneling (localhost.run):")
            print("\n   qrtunnel <files> --noauth")
            print("\nThis requires no authentication or sign-up!")
            print("-"*60)
        
        print("\n" + "="*60)
        
        choice = input("\nDo you have an ngrok authtoken? (y/n): ").strip().lower()
        
        if choice == 'y':
            print("\n📋 Paste your ngrok authtoken below:")
            authtoken = input("Authtoken: ").strip()
            
            if authtoken and len(authtoken) > 20:
                self.save_authtoken(authtoken)
                print("\n✓ Authtoken saved successfully!")
                print(f"   Config location: {self.config_file}")
                return authtoken
            else:
                print("\n✗ Invalid authtoken. Please try again.")
                return None
        else:
            print("\n[OPTIONS]:")
            print("  1. Sign up at: https://dashboard.ngrok.com/signup")
            print("  2. Run 'qrtunnel --setup' after you get your authtoken")
            if platform.system() != 'Windows':
                print("  3. OR use: qrtunnel <files> --noauth (no sign-up needed!)")
            return None
    
    def verify_token(self, token):
        """Verify ngrok token by attempting to set it"""
        try:
            from pyngrok import ngrok, conf
            ngrok.set_auth_token(token)
            return True
        except Exception as e:
            print(f"✗ Token verification failed: {e}")
            return False


class NgrokTunnel:
    """Ngrok tunnel with authentication"""
    
    def __init__(self, local_port, auth_manager):
        self.local_port = local_port
        self.auth_manager = auth_manager
        self.public_url = None
        self.tunnel = None
        self.name = "ngrok"
        
    def start(self):
        """Start ngrok tunnel with authentication"""
        try:
            from pyngrok import ngrok, conf
            
            print(f"\n[*] Starting ngrok tunnel...")
            
            # Get authtoken
            authtoken = self.auth_manager.get_authtoken()
            
            if not authtoken:
                print("[!] No ngrok authtoken found")
                
                # Show helpful message about --noauth alternative
                if platform.system() != 'Windows':
                    print("\n" + "="*60)
                    print("💡 TIP: You can skip ngrok sign-up!")
                    print("="*60)
                    print("\nRestart the program with --noauth flag to use SSH tunneling")
                    print("(localhost.run) which requires NO authentication or sign-up:")
                    print("\n   qrtunnel <your_files> --noauth")
                    print("\nOr continue below to set up ngrok (requires free account).")
                    print("="*60 + "\n")
                
                authtoken = self.auth_manager.setup_ngrok_account()
                
                if not authtoken:
                    print("[!] Cannot start ngrok without authtoken")
                    if platform.system() != 'Windows':
                        print("\n💡 Remember: You can use --noauth to skip authentication!")
                        print("   Example: qrtunnel myfile.pdf --noauth")
                    return False
            
            # Set authtoken
            try:
                ngrok.set_auth_token(authtoken)
            except Exception as e:
                print(f"[!] Error setting authtoken: {e}")
                print("[*] Your saved token might be invalid. Let's set it up again.")
                authtoken = self.auth_manager.setup_ngrok_account()
                if not authtoken:
                    return False
                ngrok.set_auth_token(authtoken)
            
            # Configure ngrok
            conf.get_default().log_level = "ERROR"
            
            # Start tunnel
            print("[*] Establishing tunnel...")
            self.tunnel = ngrok.connect(self.local_port, bind_tls=True)
            self.public_url = self.tunnel.public_url
            
            # Ensure HTTPS
            if self.public_url.startswith('http://'):
                self.public_url = self.public_url.replace('http://', 'https://')
            
            print(f"✓ Tunnel established: {self.public_url}")
            return True
            
        except ImportError:
            print("✗ Error: pyngrok is not installed")
            print("   Install with: pip install pyngrok")
            return False
        except Exception as e:
            error_msg = str(e).lower()
            
            if 'authtoken' in error_msg or 'unauthorized' in error_msg or 'invalid' in error_msg:
                print(f"✗ Authentication error: {e}")
                print("\n[*] Your authtoken might be invalid or expired.")
                
                # Show --noauth alternative
                if platform.system() != 'Windows':
                    print("\n" + "="*60)
                    print("💡 ALTERNATIVE: Skip authentication entirely!")
                    print("="*60)
                    print("\nYou can restart with --noauth to use SSH tunneling:")
                    print("\n   qrtunnel <your_files> --noauth")
                    print("\nNo sign-up or authentication required!")
                    print("="*60)
                
                print("\n[*] Or let's set up your ngrok authtoken again...")
                authtoken = self.auth_manager.setup_ngrok_account()
                if authtoken:
                    # Try one more time with new token
                    try:
                        from pyngrok import ngrok
                        ngrok.set_auth_token(authtoken)
                        self.tunnel = ngrok.connect(self.local_port, bind_tls=True)
                        self.public_url = self.tunnel.public_url
                        if self.public_url.startswith('http://'):
                            self.public_url = self.public_url.replace('http://', 'https://')
                        print(f"✓ Tunnel established: {self.public_url}")
                        return True
                    except Exception as retry_error:
                        print(f"✗ Still failed: {retry_error}")
                        if platform.system() != 'Windows':
                            print("\n💡 Try restarting with: qrtunnel <files> --noauth")
                        return False
                return False
            else:
                print(f"✗ Error starting ngrok: {e}")
                return False
    
    def stop(self):
        """Stop ngrok tunnel"""
        if self.tunnel:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(self.tunnel.public_url)
                print("\n[*] Ngrok tunnel closed")
            except:
                pass


class SSHTunnel:
    """SSH-based tunnel (localhost.run - no auth required)"""
    
    def __init__(self, local_port):
        self.local_port = local_port
        self.process = None
        self.public_url = None
        self.name = "localhost.run"
        self.output_thread = None
        self.url_found = threading.Event()
        
    def check_ssh(self):
        """Check if SSH is available"""
        try:
            subprocess.run(['ssh', '-V'], capture_output=True, timeout=2)
            return True
        except:
            return False
    
    def _read_output(self):
        """Read output from SSH process in background thread"""
        url_pattern = re.compile(r'https://[a-zA-Z0-9.-]+\.lhr\.life')
        
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                
                line = line.strip()
                if line:
                    # Look for URL in the output
                    match = url_pattern.search(line)
                    if match and not self.public_url:
                        self.public_url = match.group(0)
                        self.url_found.set()
        except:
            pass
    
    def start(self):
        """Start SSH tunnel"""
        if not self.check_ssh():
            print(f"[!] SSH not available, skipping {self.name}")
            return False
        
        print(f"[*] Trying {self.name} (no auth required)...")
        
        cmd = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ServerAliveInterval=60',
            '-o', 'ConnectTimeout=15',
            '-o', 'LogLevel=ERROR',
            '-T',
            '-R', f'80:localhost:{self.local_port}',
            'nokey@localhost.run'
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Start background thread to read output
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            
            # Wait for URL with timeout
            if self.url_found.wait(timeout=20):
                print(f"✓ Connected via {self.name}: {self.public_url}")
                return True
            else:
                print(f"[!] {self.name} timeout - no URL received")
                self.stop()
                return False
            
        except Exception as e:
            print(f"[!] {self.name} error: {e}")
            self.stop()
            return False
    
    def stop(self):
        """Stop SSH tunnel"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                try:
                    self.process.kill()
                except:
                    pass
            self.process = None
            print("\n[*] SSH tunnel closed")


class TunnelManager:
    """Manages tunnel services"""
    
    def __init__(self, local_port, noauth=False):
        self.local_port = local_port
        self.active_tunnel = None
        self.public_url = None
        self.auth_manager = NgrokAuth()
        self.noauth = noauth
        
    def start(self):
        """Start tunnel based on mode"""
        print("\n" + "="*60)
        print("ESTABLISHING PUBLIC TUNNEL")
        print("="*60)
        
        if self.noauth:
            # Try SSH tunnel first (localhost.run)
            ssh_tunnel = SSHTunnel(self.local_port)
            if ssh_tunnel.start():
                self.active_tunnel = ssh_tunnel
                self.public_url = ssh_tunnel.public_url
                print("="*60)
                return True
            else:
                print("\n[!] No-auth SSH tunnel failed. Falling back to ngrok...")
                print("="*60)
        
        # Use ngrok (default or fallback)
        ngrok_tunnel = NgrokTunnel(self.local_port, self.auth_manager)
        if ngrok_tunnel.start():
            self.active_tunnel = ngrok_tunnel
            self.public_url = ngrok_tunnel.public_url
            print("="*60)
            return True
        
        print("="*60)
        print("\n✗ All tunnel services failed")
        print("\n[SOLUTIONS]:")
        if platform.system() != 'Windows':
            print("  1. 🚀 EASIEST: Restart with --noauth (no sign-up required!)")
            print("     Example: qrtunnel <your_files> --noauth")
            print()
        print("  2. Make sure you have a valid ngrok authtoken")
        print("  3. Run: qrtunnel --setup (to configure ngrok)")
        print("  4. Check your internet connection")
        print("  5. Check your firewall settings")
        return False
    
    def stop(self):
        """Stop active tunnel"""
        if self.active_tunnel:
            self.active_tunnel.stop()


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
        print("\n" + "="*60)
        print("⚠️  QR code library not installed")
        print("Install with: pip install qrcode[pil]")
        print("="*60)
        print(f"\n🌐 URL: {url}")
        print("="*60 + "\n")


def format_size(bytes):
    """Format bytes to human-readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="qrtunnel: Simple cross-platform file sharing via QR code with ngrok.",
        usage="qrtunnel <file_path1> [<file_path2> ...] [options]"
    )
    parser.add_argument('file_paths', nargs='*', help='One or more paths to the files you want to share.')
    parser.add_argument('--setup', action='store_true', help='Set up or reconfigure ngrok authtoken')
    parser.add_argument('--status', action='store_true', help='Check authentication status')
    parser.add_argument('--noauth', action='store_true', help='Use SSH tunnel (localhost.run) without authentication (Mac/Linux only)')
    
    args = parser.parse_args()
    
    # Handle setup mode
    if args.setup:
        auth = NgrokAuth()
        token = auth.setup_ngrok_account()
        if token:
            print("\n✓ Setup complete! You can now use qrtunnel to share files.")
        else:
            print("\n✗ Setup incomplete. Please try again.")
        sys.exit(0 if token else 1)
    
    # Handle status check
    if args.status:
        auth = NgrokAuth()
        token = auth.get_authtoken()
        print("\n" + "="*60)
        print("AUTHENTICATION STATUS")
        print("="*60)
        if token:
            masked_token = token[:8] + "..." + token[-4:] if len(token) > 12 else "***"
            print(f"✓ Ngrok authtoken found: {masked_token}")
            print(f"  Config location: {auth.config_file}")
        else:
            print("✗ No ngrok authtoken configured")
            print("\nTo set up ngrok:")
            print("  1. Run: qrtunnel --setup")
            print("  2. Or visit: https://dashboard.ngrok.com/get-started/your-authtoken")
        print("="*60 + "\n")
        sys.exit(0 if token else 1)
    
    # Handle --noauth on Windows
    noauth_mode = args.noauth
    if noauth_mode and platform.system() == 'Windows':
        print("\n" + "="*60)
        print("⚠️  WARNING: --noauth is not supported on Windows")
        print("="*60)
        print("\nThe --noauth option uses SSH tunneling via localhost.run,")
        print("which is not reliably supported on Windows.")
        print("\nProceeding with ngrok instead...")
        print("="*60)
        noauth_mode = False
    
    # Validate that we have files to share
    if not args.file_paths:
        parser.print_help()
        sys.exit(1)
    
    file_paths = args.file_paths
    
    # Validate files
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"✗ Error: File '{file_path}' not found")
            sys.exit(1)
        
        if not os.path.isfile(file_path):
            print(f"✗ Error: '{file_path}' is not a file")
            sys.exit(1)
    
    # Display banner
    print("\n" + "="*60)
    print("qrtunnel - Simple File Sharing")
    print(f"Platform: {platform.system()} {platform.release()}")
    if noauth_mode:
        print("Mode: No-auth (SSH tunnel via localhost.run)")
    else:
        print("Mode: ngrok (authenticated)")
    print("="*60)
    print("Files to be shared:")
    for file_path in file_paths:
        size = os.path.getsize(file_path)
        print(f"  - {os.path.basename(file_path)} ({format_size(size)})")
    print("="*60)
    
    # Set up handler with file paths
    FileShareHandler.file_paths = file_paths
    
    # Start HTTP server
    try:
        server = HTTPServer(('localhost', Config.LOCAL_PORT), FileShareHandler)
    except OSError as e:
        print(f"\n✗ Error: Could not bind to port {Config.LOCAL_PORT}")
        print(f"   {e}")
        sys.exit(1)
    
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"\n✓ HTTP server started on localhost:{Config.LOCAL_PORT}")
    
    # Start tunnel
    tunnel_manager = TunnelManager(Config.LOCAL_PORT, noauth=noauth_mode)
    
    if not tunnel_manager.start():
        server.shutdown()
        sys.exit(1)
    
    # Generate and display QR code
    generate_qr_code(tunnel_manager.public_url)
    
    print("[*] Server is running. Press 'q' to quit, or Ctrl+C to stop.\n")
    
    # Set terminal to raw mode for immediate character reading
    if platform.system() != 'Windows':
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)  # Use cbreak mode instead of raw
            
            try:
                while True:
                    import select
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        char = sys.stdin.read(1)
                        if char and char.lower() == 'q':
                            print("\n[*] 'q' pressed. Shutting down...")
                            break
            except KeyboardInterrupt:
                print("\n[*] Ctrl+C pressed. Shutting down...")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            tunnel_manager.stop()
            server.shutdown()
            print("[*] Server stopped. Goodbye!")
    else:
        # Windows version
        import msvcrt
        try:
            while True:
                if msvcrt.kbhit():
                    char = msvcrt.getch().decode('utf-8', errors='ignore')
                    if char and char.lower() == 'q':
                        print("\n[*] 'q' pressed. Shutting down...")
                        break
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[*] Ctrl+C pressed. Shutting down...")
        finally:
            tunnel_manager.stop()
            server.shutdown()
            print("[*] Server stopped. Goodbye!")


if __name__ == '__main__':
    main()
