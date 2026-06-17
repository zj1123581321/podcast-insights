#!/usr/bin/env bash
# Cloudflare Pages 构建：组装“干净发布目录” dist/ —— 只含前端 + 它需要的两个 JSON，
# 不发布 pipeline 代码、转录稿、view_urls token 文件。
#
# CF Pages 设置：
#   Build command            = bash build.sh
#   Build output directory   = dist
#   Production branch        = master
#
# 本地手动部署也可复用： bash build.sh && wrangler pages deploy dist --project-name podcast-insights
set -euo pipefail
cd "$(dirname "$0")"

rm -rf dist
mkdir -p dist/web dist/data/feihua

cp index.html dist/index.html              # 根路径跳转 -> /web/
cp -R web/. dist/web/                       # 应用 + vendor + 合规 china.geojson
cp data/feihua/recommendations_all.json data/feihua/geo.json dist/data/feihua/

echo "built dist: $(find dist -type f | wc -l) files"
