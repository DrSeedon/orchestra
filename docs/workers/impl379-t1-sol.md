# impl379-t1-sol

- Restart-path tests mock `os.kill`, so a helper armed by one test can remain alive in the
  pytest process; restart guards must explicitly retire a prior attempt when the next attempt
  arms, and the seamless-restart regression suite exposes the leak.
