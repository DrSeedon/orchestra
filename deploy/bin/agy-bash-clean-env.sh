unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY http_proxy https_proxy all_proxy grpc_proxy NO_GRPC_PROXY no_grpc_proxy BASH_ENV
if [ "${_ORCH_TOOL_EXEC_DONE:-0}" != "1" ] && [ -x /usr/local/bin/agy-clean-exec ] && [ "$(/usr/bin/id -g)" != "1001" ] && [ -S /run/orchestra-agy/tool-exec.sock ]; then
  export _ORCH_TOOL_EXEC_DONE=1
  _ORCH_CMDLINE_B64="$(/usr/bin/base64 -w0 "/proc/$$/cmdline" 2>/dev/null || true)"
  if [ -n "$_ORCH_CMDLINE_B64" ]; then
    exec /usr/local/bin/agy-clean-exec --cmdline-b64 "$_ORCH_CMDLINE_B64"
  fi
fi
