# This will expose your WebSocket server on a public URL
cloudflared tunnel run refportal-dev-tunnel &
cloudflared tunnel route dns refportal-dev-tunnel pwa-dev.refereex.com &
cloudflared tunnel route dns refportal-dev-tunnel api-dev.refereex.com &
#cloudflared tunnel --url http://localhost:8082 &
#cloudflared tunnel --url http://localhost:5002 &
# Redis TCP tunnel via Cloudflare Access
# Forwards redis.refereex.com to local Redis on port 6379
cloudflared access tcp --hostname redis.refereex.com --url localhost:2000 &
#'/Applications/Another Redis Desktop Manager.app' &
wait
