#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Q Agent Entry Point
"""

import argparse
import os
import sys

# Ensure the 'q' package directory is in the Python path
# This allows running 'python q.py' from the project root
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Only import version initially - defer other imports
from q import __version__  # noqa: E402

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Q CLI Agent")
    parser.add_argument(
        "--version", action="store_true", help="Show version information and exit"
    )
    parser.add_argument(
        "--exit-after-answer", "-e", action="store_true", 
        help="Exit after answering the initial question"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Grant execution of all commands except dangerous or prohibited ones"
    )
    parser.add_argument(
        "--recover", "-r", action="store_true",
        help="Recover previous session"
    )

    # Any remaining arguments will be treated as the initial question
    parser.add_argument("question", nargs="*", help="Initial question to ask")

    args = parser.parse_args()

    # Handle --version flag - no need to import anything else
    if args.version:
        print(f"Q CLI Agent version {__version__}")
        sys.exit(0)

    # Only import main_loop when needed - after handling simple commands like --version
    from q.main import main_loop  # noqa: E402

    # Join the question arguments into a single string
    initial_question = " ".join(args.question) if args.question else None

    # Call the main loop with the initial question, exit flag, and recover flag
    main_loop(
        initial_question=initial_question, 
        exit_after_answer=args.exit_after_answer, 
        allow_all=args.all,
        recover=args.recover
    )

if __name__ == "__main__":
    main()