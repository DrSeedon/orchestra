#!/bin/sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY http_proxy https_proxy all_proxy grpc_proxy NO_GRPC_PROXY no_grpc_proxy BASH_ENV
if [ -x /usr/local/bin/agy-clean-exec ]; then
  exec /usr/local/bin/agy-clean-exec /bin/bash "$@"
fi
exec /bin/bash "$@"
