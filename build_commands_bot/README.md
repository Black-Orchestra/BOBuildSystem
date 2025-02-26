# Build Commands Discord Bot for BOBuildSystem

## Building

### Make sure BOBuildSystem repo is cloned with submodules

```bash
git clone <REPO_URL_HERE> --recurse-submodules  
```

Or initialize them post-clone:

```bash
git submodule update --init --recursive
```

### Bootstrap vcpkg

Windows:

```powershell
.\submodules\vcpkg\bootstrap-vcpkg.bat -disableMetrics
```

Linux:

```bash
./submodules/vcpk/bootstrap-vcpkg.sh -disableMetrics
```

### Build project

List available CMake presets:

```bash
cmake --list-presets          # Configure presets.
cmake --build --list-presets  # Build presets.
```

Configure and build a preset:

```bash
cmake --preset config-windows-debug-x64
cmake --build --preset windows-debug-x64
```

## Development TODOs

- Improve CI build speeds with caching?
  - For the Docker image build?
  - Ccache?

- Boost channel try_send optimization.
