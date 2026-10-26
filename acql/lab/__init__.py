"""The Lab: a private, local-only research site for Operation Sunday.

Run it with `python -m acql.lab` and open http://127.0.0.1:8765. It is never
published - it binds to this computer only - because it shows Deadeye's own
forecasts, which stay off the public ACQL website.

    data.py       every number the pages show, read from what the app already
                  keeps (forecast log, stored scores and lines, nflverse files,
                  the raw odds archive). Nothing is fetched or written here.
    live.py       one shared ESPN poller with back-off and a last-good snapshot,
                  pushed to every open page over Server-Sent Events.
    assistant.py  a read-only research assistant: Claude with tools that call
                  data.py, never the filesystem, the shell or the model.
    server.py     the small HTTP server tying them together.
    page.html     the whole site, one file, no outside scripts.

Nothing here changes how Deadeye prices a game or touches a locked forecast.
"""
