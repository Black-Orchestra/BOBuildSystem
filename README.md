# BOBuildSystem

Automated builds and server hosting for Black Orchestra.

## Development instructions

Make sure you have at least Python 3.11 (newer is better)
installed, then run the following command to install the
project in development mode:

Clone the repository with submodules:

```bash
git clone --recurse-submodules git@github.com:tuokri/BOBuildSystem.git
```

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

## Production deployment

TODO: write deployment instructions.

## Development TODOs

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

## License

```
SPDX-License-Identifier: AGPL-3.0-or-later
```

```
Copyright (C) 2025  Tuomo Kriikkula
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```
