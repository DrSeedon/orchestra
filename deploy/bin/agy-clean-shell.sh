#!/bin/sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY http_proxy https_proxy all_proxy grpc_proxy NO_GRPC_PROXY no_grpc_proxy BASH_ENV
if [ -x /usr/local/libexec/orchestra-agy-dropgid ]; then
  exec /usr/local/libexec/orchestra-agy-dropgid /bin/bash "$@"
fi
exec /bin/bash "$@"
