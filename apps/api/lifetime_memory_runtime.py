"""Feature control for the staged lifetime-memory integration. Disabled by default."""
import os


def lifetime_enabled():
    return os.getenv('MEMOIR_LIFETIME_MEMORY','').lower() in {'1','true','yes'}
