unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY http_proxy https_proxy all_proxy grpc_proxy NO_GRPC_PROXY no_grpc_proxy BASH_ENV
if [ -x /usr/local/libexec/orchestra-agy-dropgid ] && [ "$(/usr/bin/id -g)" != "1001" ] && [ -n "${BASH_EXECUTION_STRING:-}" ]; then
  exec /usr/local/libexec/orchestra-agy-dropgid /bin/bash -c "$BASH_EXECUTION_STRING" "$0" "$@"
fi
