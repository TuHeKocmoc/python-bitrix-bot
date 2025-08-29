#!/bin/bash

echo "Stopping both bots..."

# Stop all services
docker-compose -f docker-compose-multi.yml down

echo "Services stopped!" 