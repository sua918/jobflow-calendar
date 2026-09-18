from __future__ import annotations

import os
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from jobflow.ui import build_blocks


def build_app() -> gr.Blocks:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    os.environ["GRADIO_RUN_HISTORY"] = "False"
    return build_blocks()


def main() -> None:
    app = build_app()
    app.launch(server_name="127.0.0.1")


if __name__ == "__main__":
    main()
