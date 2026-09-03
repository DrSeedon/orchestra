# research-taskmanager

- Cross-source live audits: immediately pin every repository ref after the SQLite backup and run
  reconciliation against those SHAs, not moving `main`; otherwise commits created after the DB
  snapshot look falsely taskless.
