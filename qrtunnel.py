#!/usr/bin/env python3
"""Compatibility shim for the qrtunnel package."""

from src import qrtunnel as _package

__all__ = _package.__all__


def __getattr__(name):
    return getattr(_package, name)


def main():
    from src.qrtunnel.app import main as app_main

    app_main()


if __name__ == "__main__":
    main()
