const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

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
        console.log('✅ Updated .env with clean Cloudflare URL:', webAppUrl);
    }
}

let activeProcess = null;

function startCloudflareTunnel() {
    console.log('🚀 Starting Cloudflare Tunnel (100% clean, no warning splash screen)...');
    
    let binPath = CLOUDFLARED_PATH;
    if (!fs.existsSync(binPath)) {
        binPath = 'cloudflared';
    }

    activeProcess = spawn(binPath, ['tunnel', '--url', 'http://127.0.0.1:8000'], {
        windowsHide: true
    });

    let detectedUrl = false;

    activeProcess.stderr.on('data', (data) => {
        const str = data.toString();
        // Cloudflare prints tunnel URL in stderr
        const match = str.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
        if (match && !detectedUrl) {
            detectedUrl = true;
            const tunnelUrl = match[0];
            console.log('🌟 CLOUDFLARE_TUNNEL_ONLINE:', tunnelUrl);
            updateEnv(tunnelUrl);
        }
    });

    activeProcess.on('close', (code) => {
        console.log(`Cloudflare tunnel exited with code ${code}. Reconnecting in 3 seconds...`);
        detectedUrl = false;
        setTimeout(startCloudflareTunnel, 3000);
    });

    activeProcess.on('error', (err) => {
        console.error('Cloudflare tunnel error:', err.message);
        detectedUrl = false;
        setTimeout(startCloudflareTunnel, 3000);
    });
}

process.on('SIGINT', () => {
    if (activeProcess) activeProcess.kill();
    process.exit();
});
process.on('SIGTERM', () => {
    if (activeProcess) activeProcess.kill();
    process.exit();
});

startCloudflareTunnel();
