#!/bin/bash
# NapCat 守护脚本 — 确保 Docker Desktop 和 NapCat 容器持续运行
# 用法: nohup bash scripts/keep-napcat-alive.sh &

INTERVAL=30

while true; do
    # 检查 Docker 是否在运行
    if ! docker info &>/dev/null; then
        echo "[$(date)] Docker not running, starting..."
        open -a Docker
        # 等待 Docker 就绪
        for i in $(seq 1 30); do
            docker info &>/dev/null && break
            sleep 2
        done
        if ! docker info &>/dev/null; then
            echo "[$(date)] Docker failed to start, retrying in ${INTERVAL}s..."
            sleep $INTERVAL
            continue
        fi
        echo "[$(date)] Docker is ready"
    fi

    # 检查 NapCat 容器是否在运行
    STATUS=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null)
    if [ "$STATUS" != "true" ]; then
        echo "[$(date)] NapCat not running, starting container..."
        docker start napcat 2>/dev/null || echo "[$(date)] Failed to start napcat"
    fi

    sleep $INTERVAL
done
