#!/usr/bin/env bash

# ls -lah
# find . -name "*build_commands_bot"
# find . -name "*.so*"
# find . -name "*.a*"

export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:./

./build_commands_bot
