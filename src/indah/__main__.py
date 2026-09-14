"""`python -m indah` launches the built-in demo app.

Binds the first free port from 8000 up, prints the URL, and serves until
interrupted. This is what `make demo` runs.
"""

from .launch import launch

if __name__ == "__main__":
    launch()
