"""
Avtomatlashtirilgan va Uzluksiz Tunnel Skripti (Cloudflare Quick & Named Tunnel).
1. 8008 portni (GiftHub FastAPI WebApp) internetga ulaydi
2. .env fayliga yangi ADMIN_APP_URL va WEB_APP_URL ni o'zi yozib qo'yadi
3. Uzilib qolmaydi, HTTP/2 protokoli bilan barqaror ishlaydi
"""
import os
import re
import subprocess
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    except Exception as e:
        sys.stderr.write(f"Warning: Stdout reconfigure failed: {e}\n")


try:
    from app.core.config import settings
    PORT = settings.WEB_PORT
except Exception:
    PORT = 8000


def update_env(tunnel_url):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    admin_url = f"{tunnel_url}/admin"
    app_url = f"{tunnel_url}/app"
    
    if "ADMIN_APP_URL=" in content:
        content = re.sub(r"ADMIN_APP_URL=.*", f"ADMIN_APP_URL={admin_url}", content)
    else:
        content += f"\nADMIN_APP_URL={admin_url}"

    if "WEB_APP_URL=" in content:
        content = re.sub(r"WEB_APP_URL=.*", f"WEB_APP_URL={app_url}", content)
    else:
        content += f"\nWEB_APP_URL={app_url}"
    
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n[OK] .env yangilandi:\n  - ADMIN_APP_URL={admin_url}\n  - WEB_APP_URL={app_url}")

def get_cloudflared_command():
    # .env dan Cloudflare Tunnel Token tekshirish
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    token = None
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("CLOUDFLARE_TUNNEL_TOKEN="):
                    val = line.split("=", 1)[1].strip()
                    if len(val) > 20:
                        token = val
                        break

    bin_name = "cloudflared.cmd" if os.name == "nt" else "cloudflared"

    if token:
        print("[*] Cloudflare Zero Trust Named Tunnel rejimida ishlamoqda (Token bilan)...")
        return [bin_name, "tunnel", "run", "--token", token]
    else:
        print(f"[*] Cloudflare Quick Tunnel ishga tushirilmoqda (localhost:{PORT})...")
        return [bin_name, "tunnel", "--protocol", "http2", "--edge-ip-version", "4", "--url", f"http://localhost:{PORT}"]

def run_cloudflare_tunnel():
    print("=" * 65)

    # Eski yetim qolgan cloudflared jarayonlarini tozalash
    if os.name == "nt":
        subprocess.run("taskkill /F /IM cloudflared.exe >nul 2>&1", shell=True)

    cmd = get_cloudflared_command()
    
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
        shell=True,
    )

    url_found = False
    try:
        for line in iter(proc.stdout.readline, ''):
            print(line, end='')
            if not url_found:
                # api.trycloudflare.com ni inkor qilib, faqat haqiqiy subdomenni ushlaymiz
                matches = re.findall(r'https://[a-zA-Z0-9\.\-_]+\.trycloudflare\.com', line)
                for url in matches:
                    if "api.trycloudflare.com" not in url:
                        url_found = True
                        update_env(url)
                        print("\n" + "=" * 65)
                        print("🎉 [SUCCESS] CLOUDFLARE HTTPS TUNNEL TAYYOR!")
                        print(f"🔗 Admin Web App: {url}/admin")
                        print("=" * 65 + "\n")
                        break
        proc.wait()
    except KeyboardInterrupt:
        print("\nTunnel to'xtatildi.")
        if os.name == "nt":
            subprocess.run(f"taskkill /F /T /PID {proc.pid} >nul 2>&1", shell=True)
            subprocess.run("taskkill /F /IM cloudflared.exe >nul 2>&1", shell=True)
        else:
            proc.terminate()
        return False

    return True

def main():
    while True:
        should_continue = run_cloudflare_tunnel()
        if not should_continue:
            break
        print("\n[!] Tunnel uzildi. 3 soniyadan so'ng avtomatik qayta ulanadi...")
        time.sleep(3)

if __name__ == "__main__":
    main()
