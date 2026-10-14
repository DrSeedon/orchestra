# V-842 — upload chip screenshots

Playwright screenshots use the isolated dashboard fixture and a temporary SQLite database. The file list uses the original names shown in the owner's screenshot, with nonzero sizes; an existing 39 KB JPEG photo is used for the image thumbnail. Viewports are 1440×960 and 390×844.

| Viewport | Files | Screenshot | Panel | Content | Columns |
|---|---:|---|---:|---:|---:|
| Desktop | 1 | [desktop-1.png](desktop-1.png) | 68 px | 68 px | 3 |
| Desktop | 11 | [desktop-11.png](desktop-11.png) | 136 px | 260 px | 3 |
| Desktop | 25 | [desktop-25.png](desktop-25.png) | 136 px | 580 px | 3 |
| Phone | 1 | [mobile-1.png](mobile-1.png) | 62 px | 62 px | 2 |
| Phone | 11 | [mobile-11.png](mobile-11.png) | 124 px | 347 px | 2 |
| Phone | 25 | [mobile-25.png](mobile-25.png) | 124 px | 746 px | 2 |

All six runs had a visible image thumbnail, one download control per card, an active scroll hint whenever content exceeded the panel, and zero gap between panel and composer. Long names show the beginning and ending portion with the extension retained; download and remove controls occupy separate positions.
