const localtunnel = require('localtunnel');
const fs = require('fs');
const path = require('path');

const SUBDOMAIN = 'stellar-bot-uz-app';

async function connect() {
    try {
        console.log(`Connecting tunnel with subdomain ${SUBDOMAIN}...`);
        const tunnel = await localtunnel({ port: 8000, subdomain: SUBDOMAIN });
        console.log('TUNNEL_ONLINE:', tunnel.url);
        
        // Update .env if url changed
        const envPath = path.join(__dirname, '.env');
        if (fs.existsSync(envPath)) {
            let envContent = fs.readFileSync(envPath, 'utf8');
            const webAppUrl = `${tunnel.url}/app`;
            const adminAppUrl = `${tunnel.url}/admin`;
            envContent = envContent.replace(/WEB_APP_URL=.*/, `WEB_APP_URL=${webAppUrl}`);
            envContent = envContent.replace(/ADMIN_APP_URL=.*/, `ADMIN_APP_URL=${adminAppUrl}`);
            fs.writeFileSync(envPath, envContent, 'utf8');
            console.log('Updated .env with:', webAppUrl);
        }

        tunnel.on('close', () => {
            console.log('Tunnel closed. Reconnecting in 3 seconds...');
            setTimeout(connect, 3000);
        });
        tunnel.on('error', (err) => {
            console.error('Tunnel error:', err.message);
            try { tunnel.close(); } catch(e) {}
            setTimeout(connect, 3000);
        });
    } catch (err) {
        console.error('Tunnel startup error:', err.message);
        setTimeout(connect, 3000);
    }
}

connect();
