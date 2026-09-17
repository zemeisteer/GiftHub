const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');

const CLOUDFLARED_PATH = 'C:/Users/user/AppData/Roaming/npm/node_modules/cloudflared/bin/cloudflared.exe';

function updateEnv(tunnelUrl) {
    const envPath = path.join(__dirname, '.env');
    if (fs.existsSync(envPath)) {
        let envContent = fs.readFileSync(envPath, 'utf8');
        const webAppUrl = `${tunnelUrl}/app`;
        const adminAppUrl = `${tunnelUrl}/admin`;
        envContent = envContent.replace(/WEB_APP_URL=.*/, `WEB_APP_URL=${webAppUrl}`);
        envContent = envContent.replace(/ADMIN_APP_URL=.*/, `ADMIN_APP_URL=${adminAppUrl}`);
        fs.writeFileSync(envPath, envContent, 'utf8');
        console.log('✅ Updated .env with clean Cloudflare URL:', adminAppUrl);
    }
}

let activeProcess = null;
let currentTunnelUrl = null;
let watchdogInterval = null;
let consecutiveFailures = 0;

function checkTunnelHealth() {
    if (!currentTunnelUrl) return;
    const testUrl = `${currentTunnelUrl}/api/bot-info`;
    const req = https.get(testUrl, { timeout: 8000 }, (res) => {
        if (res.statusCode >= 200 && res.statusCode < 500) {
            consecutiveFailures = 0;
        } else {
            consecutiveFailures++;
            handleFailures();
        }
    });
    req.on('error', () => {
        consecutiveFailures++;
        handleFailures();
    });
    req.on('timeout', () => {
        req.destroy();
        consecutiveFailures++;
        handleFailures();
    });
}

function handleFailures() {
    if (consecutiveFailures >= 2) {
        console.log('⚠️ Tunnel health check failed 2 times! Re-spawning Cloudflare tunnel...');
        consecutiveFailures = 0;
        currentTunnelUrl = null;
        if (activeProcess) {
            try { activeProcess.kill(); } catch (e) {}
        }
    }
}

function startCloudflareTunnel() {
    console.log('🚀 Starting Cloudflare Tunnel (100% clean, with auto-healing watchdog)...');

    let binPath = CLOUDFLARED_PATH;
    if (!fs.existsSync(binPath)) {
        binPath = 'cloudflared';
    }

    activeProcess = spawn(binPath, ['tunnel', '--url', 'http://127.0.0.1:8008'], {
        windowsHide: true
    });

    let detectedUrl = false;

    activeProcess.stderr.on('data', (data) => {
        const str = data.toString();
        const match = str.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
        if (match && !detectedUrl) {
            detectedUrl = true;
            currentTunnelUrl = match[0];
            consecutiveFailures = 0;
            console.log('🌟 CLOUDFLARE_TUNNEL_ONLINE:', currentTunnelUrl);
            updateEnv(currentTunnelUrl);
        }
    });

    activeProcess.on('close', (code) => {
        console.log(`Cloudflare tunnel exited with code ${code}. Reconnecting in 3 seconds...`);
        detectedUrl = false;
        currentTunnelUrl = null;
        setTimeout(startCloudflareTunnel, 3000);
    });

    activeProcess.on('error', (err) => {
        console.error('Cloudflare tunnel error:', err.message);
        detectedUrl = false;
        currentTunnelUrl = null;
        setTimeout(startCloudflareTunnel, 3000);
    });
}

if (!watchdogInterval) {
    watchdogInterval = setInterval(checkTunnelHealth, 20000);
}

process.on('SIGINT', () => {
    if (watchdogInterval) clearInterval(watchdogInterval);
    if (activeProcess) activeProcess.kill();
    process.exit();
});
process.on('SIGTERM', () => {
    if (watchdogInterval) clearInterval(watchdogInterval);
    if (activeProcess) activeProcess.kill();
    process.exit();
});

startCloudflareTunnel();
