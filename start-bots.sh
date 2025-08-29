#!/bin/bash

echo "Starting both bots with shared monitoring services..."

# Load environment variables
if [ -f "env.multi" ]; then
    export $(cat env.multi | grep -v '^#' | xargs)
fi

# Start all services
docker compose -f docker-compose-multi.yml up -d

echo "Services started!"
echo ""
echo "Services status:"
docker compose -f docker-compose-multi.yml ps
echo ""
echo "Access points:"
echo "- Grafana: http://localhost:3000"
echo "- Prometheus: http://localhost:9090"
echo "- Bitrix Bot metrics: http://localhost:8000"
echo "- Task Bot metrics: http://localhost:8001"
echo ""
echo "To view logs:"
echo "- Bitrix bot: docker-compose -f docker-compose-multi.yml logs -f bot-bitrix"
echo "- Task bot: docker-compose -f docker-compose-multi.yml logs -f bot-task" 