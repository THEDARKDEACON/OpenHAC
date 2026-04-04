# Auto-configure KiCad 8 environment before any SKiDL usage
from .env_setup import bootstrap_environment as _bootstrap_environment
_bootstrap_environment()

from .board import Board
from .base import Component, Module, Interface
