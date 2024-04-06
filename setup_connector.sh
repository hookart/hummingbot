#!/bin/bash

echo "Setting up connector..."
if [ -z "$CONNECTOR_FILE_NAME" ]; then
  exit 1
fi

if [ -z "$CONNECTOR_DEST_FILE_NAME" ]; then
  exit 1
fi

SOURCE_FILE="conf/connectors/$CONNECTOR_FILE_NAME"
DEST_FILE="conf/connectors/$CONNECTOR_DEST_FILE_NAME"

if [ ! -f "$SOURCE_FILE" ]; then
  exit 1
fi

mv "$SOURCE_FILE" "$DEST_FILE"
