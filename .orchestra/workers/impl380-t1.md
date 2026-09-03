# impl380-t1

- In `app/routes/*`, route handler names can shadow imported `app.db` helpers at runtime; alias imports such as `get_session as get_session_row` when adding route logic.
