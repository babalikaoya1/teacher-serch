#!/bin/sh
# 在 deploy 目录运行；备份文件必须另行复制到独立存储。
set -eu
mkdir -p backups
backup_path="backups/teacher-$(date -u +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U teacher -d teacher --format=custom > "$backup_path"
printf '备份已生成：%s\n' "$backup_path"
