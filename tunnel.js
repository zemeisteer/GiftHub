const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const CLOUDFLARED_PATH = 'C:/Users/user/AppData/Roaming/npm/node_modules/cloudflared/bin/cloudflared.exe';
const ENV_PATH = path.join(__dirname, '.env');

function getEnvValue(key) {
    if (!fs.existsSync(ENV_PATH)) return null;
    const content = fs.readFileSync(ENV_PATH, 'utf8');
    const match = content.match(new RegExp(`^${key}=(.*)$`, 'm'));
    return match ? match[1].trim() : null;
}

function updateEnvUrls(tunnelUrl) {
    if (!fs.existsSync(ENV_PATH)) return;
    let envContent = fs.readFileSync(ENV_PATH, 'utf8');
    const webAppUrl = `${tunnelUrl}/app`;
    const adminAppUrl = `${tunnelUrl}/admin`;
    
    if (envContent.includes('WEB_APP_URL=')) {
        envContent = envContent.replace(/WEB_APP_URL=.*/, `WEB_APP_URL=${webAppUrl}`);
    } else {
        envContent += `\nWEB_APP_URL=${webAppUrl}`;
    }

    if (envContent.includes('ADMIN_APP_URL=')) {
        envContent = envContent.replace(/ADMIN_APP_URL=.*/, `ADMIN_APP_URL=${adminAppUrl}`);
    } else {
        envContent += `\nADMIN_APP_URL=${adminAppUrl}`;
    }

    fs.writeFileSync(ENV_PATH, envContent, 'utf8');
    console.log('✅ Updated .env:');
    console.log('   - ADMIN_APP_URL:', adminAppUrl);
    console.log('   - WEB_APP_URL:  ', webAppUrl);
}

let activeProcess = null;
let reconnectTimer = null;

function getCloudflaredBin() {
    if (fs.existsSync(CLOUDFLARED_PATH)) {
        return CLOUDFLARED_PATH;
    }
    return 'cloudflared';
}

function startTunnel() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    const bin = getCloudflaredBin();
    const token = getEnvValue('CLOUDFLARE_TUNNEL_TOKEN');

    if (token && token.length > 20) {
        console.log('🔒 Starting Cloudflare Permanent Named Tunnel with Zero Trust token...');
        activeProcess = spawn(bin, ['tunnel', 'run', '--token', token], {
            windowsHide: true
        });
    } else {
        console.log('🌐 Starting Cloudflare Quick Tunnel (Optimized IPv4, no auto-kill)...');
        activeProcess = spawn(bin, [
            'tunnel',
            '--url', 'http://127.0.0.1:8008',
            '--edge-ip-version', '4',
            '--no-autoupdate'
        ], {
            windowsHide: true
        });
    }

    let detectedUrl = false;

    function handleOutput(data) {
        const str = data.toString();

        // Extract valid *.trycloudflare.com URLs, strictly excluding api.trycloudflare.com
        const matches = str.match(/https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com/g);
        if (matches) {
            for (const url of matches) {
                if (!url.includes('api.trycloudflare.com') && !detectedUrl) {
                    detectedUrl = true;
                    console.log('\n======================================================');
                    console.log('🌟 CLOUDFLARE TUNNEL ONLINE:');
                    console.log('   URL:', url);
                    console.log('   Admin App:', `${url}/admin`);
                    console.log('======================================================\n');
                    updateEnvUrls(url);
                    break;
                }
            }
        }
    }

    activeProcess.stdout.on('data', handleOutput);
    activeProcess.stderr.on('data', handleOutput);

    activeProcess.on('close', (code) => {
        console.log(`⚠️ Cloudflare tunnel process exited (code: ${code}). Auto-reconnecting in 3s...`);
        activeProcess = null;
        detectedUrl = false;
        reconnectTimer = setTimeout(startTunnel, 3000);
    });

    activeProcess.on('error', (err) => {
        console.error('❌ Cloudflare tunnel process error:', err.message);
        activeProcess = null;
        detectedUrl = false;
        reconnectTimer = setTimeout(startTunnel, 3000);
    });
}

function cleanup() {
    console.log('\n🛑 Stopping tunnel daemon...');
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (activeProcess) {
        try {
            activeProcess.kill('SIGINT');
        } catch (e) {}
        activeProcess = null;
    }
    process.exit();
}

process.on('SIGINT', cleanup);
process.on('SIGTERM', cleanup);

startTunnel();
