# BOBuildSystem

## Development instructions

Make sure you have at least Python 3.11 (newer is better)
installed, then run the following command to install the
project in development mode:

```bash
# From root directory of this repo:
pip install -e .[dev]
```

When doing changes, make sure type hints and type safety
is at least mostly correct. Type errors and warnings
should only be silenced if there is no proper fix for them.
Use mypy to check for typing errors:

```bash
# From root directory of this repo:
mypy .
```

Use ruff to lint code:
```bash
# From root directory of this repo:
ruff check .
```

## TODO

Setup script to run BO server as a Windows service:

1. fetch BO packages (check result)
2. fetch BO maps (check result)
3. get latest code from github (check result)
4. compile code (check result)
5. cook the entire mod (check result)
6. stop running server(s) (check result)
7. move updated files to server (check result)
8. start server(s) (check result)

9. optional: upload files to workshop

Optional: get the files from workshop
