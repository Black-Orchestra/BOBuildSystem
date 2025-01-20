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
mypy --install-types  # Only need to run this once, or after adding new packages!
mypy .
```

Use ruff to lint code:

```bash
# From root directory of this repo:
ruff check .
```

## Production deployment

Deployment requires Windows on the main worker machine to run VNEditor.exe.
Some services like Redis, Postgres, task scheduler, etc. can be run on Linux/Docker.

TODO: it's probably possible to run VNEditor.exe on Linux using Wine.

### Environment variables

Several environment variables are required to be set in production deployment.
TODO: document these.

## Development TODOs

- Setup script to run BO server as a Windows service.
- Server installation:
    - Make sure up to date DLLs are fetched from Steam.
    - Make sure server configuration is correct:
        - WebAdmin enabled, correct port.
        - Suppression of useful logs removed.
        - Chat logs, etc. enabled.
    - Make sure GAM packages are installed!
- Server workshop handling:
    - Private items -> can't leverage built-in SWS downloader?
        - Try to download them manually with SteamCMD.
        - Still put them in server's list of SWS items?
        - What happens to clients who can see the items when they join
          the server, but the server itself can't see them? The server
          will still have the files. Investigate.

- Investigate using free-threaded Python once all the dependencies
  support it. This is probably only possible in the far future.

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
