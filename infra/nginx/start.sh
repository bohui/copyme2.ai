#!/bin/sh

set -eu

gateway="$(ip route | awk '$1 == "default" { print $3; exit }')"
export MEMORY_SPARK_API_ORIGIN="http://${gateway}:${MEMORY_SPARK_API_PORT}"

until wget -q -O /dev/null "${MEMORY_SPARK_API_ORIGIN}/health"; do
    sleep 1
done

envsubst '$MEMORY_SPARK_API_ORIGIN' \
    < /etc/nginx/templates/memory-spark.conf.template \
    > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
