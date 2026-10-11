"""Task-owned bounded public-source process. Never receives personal context."""
import json
import sys
from .historical_news_provider import inspect_public_source

if __name__=='__main__':
    try:
        if len(sys.argv)!=3:raise ValueError()
        timeout=float(sys.argv[2])
        if not 0<timeout<=45:raise ValueError()
        print(json.dumps(inspect_public_source(sys.argv[1],timeout),ensure_ascii=False))
    except Exception:
        sys.exit(1)  # No raw provider/source errors or credentials in diagnostics.
