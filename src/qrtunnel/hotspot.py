"""Wi-Fi hotspot QR configuration helpers."""

import json

from .config import Config
from .constants import ERR, OK


# ─────────────────────────────────────────────────────────
#  HOTSPOT HELPER  (preserved)
# ─────────────────────────────────────────────────────────
class HotspotHelper:
    def __init__(self):
        self.config_file = Config.CONFIG_FILE

    def load_config(self):
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self, config):
        Config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

    def setup_interactive(self):
        print("\n" + "=" * 60)
        print("WI-FI HOTSPOT SETUP")
        print("=" * 60)
        try:
            ssid = input("SSID (Network Name): ").strip()
            if not ssid:
                print(f"{ERR} SSID cannot be empty.")
                return
            print("\nSecurity Type:")
            print("  1. WPA/WPA2/WPA3 (Most common)")
            print("  2. WEP (Old)")
            print("  3. None (Open)")
            sec_choice = input("Select [1-3] (default 1): ").strip()
            security = "WPA"
            if sec_choice == "2":
                security = "WEP"
            elif sec_choice == "3":
                security = "nopass"
            password = ""
            if security != "nopass":
                password = input("Password: ").strip()
            config = self.load_config()
            config["hotspot"] = {"ssid": ssid, "password": password, "security": security}
            self.save_config(config)
            print(f"\n{OK} Hotspot configuration saved.")
        except KeyboardInterrupt:
            print("\n\n[*] Setup cancelled.")

    def get_qr_data(self):
        config = self.load_config().get("hotspot")
        if not config:
            return None
        ssid = config.get("ssid")
        password = config.get("password", "")
        security = config.get("security", "WPA")
        if not ssid:
            return None

        def escape(s):
            return (
                s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace(":", "\\:")
            )

        qr_str = f"WIFI:T:{security};S:{escape(ssid)};"
        if security != "nopass":
            qr_str += f"P:{escape(password)};"
        qr_str += "H:false;;"
        return qr_str, ssid, password
