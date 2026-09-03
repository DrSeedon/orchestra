# fix-summary-detail

- When a live API response is wrong despite a fixed projection seam, trace the complete production caller path (including runtime fallbacks) and mutate each candidate seam; a parallel legacy-shadow path can bypass the newer projection entirely.
