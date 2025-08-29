#!/bin/bash

echo "=== Multi-Bot Status Check ==="
echo ""

# Check if services are running
if docker compose -f docker-compose-multi.yml ps | grep -q "Up"; then
    echo "✅ Services are running:"
    echo ""
    docker compose -f docker-compose-multi.yml ps
else
    echo "❌ No services are running"
    echo "Run './start-bots.sh' to start the services"
    exit 1
fi

echo ""
echo "=== Service Health Check ==="
echo ""

# Check each service individually
services=("db-bitrix" "db-task" "bot-bitrix" "bot-task" "prometheus" "grafana")

for service in "${services[@]}"; do
    if docker compose -f docker-compose-multi.yml ps | grep -q "$service.*Up"; then
        echo "✅ $service: Running"
    else
        echo "❌ $service: Not running"
    fi
done

echo ""
echo "=== Port Status ==="
echo ""

# Check if ports are accessible
ports=("3000:grafana" "9090:prometheus" "8000:bitrix-bot" "8001:task-bot")

for port_info in "${ports[@]}"; do
    port="${port_info%:*}"
    service="${port_info#*:}"
    
    if netstat -tuln 2>/dev/null | grep -q ":$port "; then
        echo "✅ Port $port ($service): Available"
    else
        echo "❌ Port $port ($service): Not available"
    fi
done

echo ""
echo "=== Quick Commands ==="
echo "View logs: ./logs-bots.sh"
echo "Stop services: ./stop-bots.sh"
echo "Restart specific service: docker compose -f docker-compose-multi.yml restart <service-name>"
