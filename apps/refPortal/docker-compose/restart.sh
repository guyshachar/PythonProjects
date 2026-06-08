app=refportalservice
app_env=prod

ver=

force_redeploy=

echo "pull image"
sudo docker image pull guyshacharacc/refportalgw:latest-${app_env}
#sudo docker image pull guyshacharacc/refportalapi:latest-${app_env}
#sudo docker image pull guyshacharacc/refportalpwa:latest-${app_env}

echo "deploy stack"
if [ "$force_redeploy" = "f" ]; then
  REDEPLOY_ID=$(date +%s)
  echo "force redeploy with REDEPLOY_ID=$REDEPLOY_ID"
  # Swarm DNS: {stack}_{service} — same default as docker-compose-srv.yml (override TAILSCALE_SOCKS_HOST if needed).
  TS_PROXY_HOST="${TAILSCALE_SOCKS_HOST:-${app}_stack_tailscale}"
  sudo APP_REPLICAS=1 REDEPLOY_ID="$REDEPLOY_ID" PROXY_SERVER="socks5h://${TS_PROXY_HOST}:1055" docker stack deploy --with-registry-auth --resolve-image always -c ~/refPortalService/docker-compose.yml ${app}_stack
else
  sudo docker service rm ${app}_stack_gw
  sudo APP_REPLICAS=1 docker stack deploy --with-registry-auth --resolve-image always -c ./docker-compose-srv.yml ${app}_stack
  sudo docker service logs ${app}_stack_gw -f -t --raw --since="10m"
fi

#sleep 5
#echo "show logs"
#~/refPortalService/run_logs.sh
