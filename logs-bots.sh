#!/bin/bash

echo "Showing logs for both bots..."
echo "Press Ctrl+C to stop viewing logs"
echo ""

# Show logs for both bots
docker-compose -f docker-compose-multi.yml logs -f bot-bitrix bot-task 