"""Connect to Memoir's existing local Langfuse project without logging keys."""

from pathlib import Path


def prompt_client(credential_file: Path | None = None):
    from langfuse import Langfuse

    if credential_file is None:
        return Langfuse()
    from dotenv import dotenv_values

    values = dotenv_values(credential_file, interpolate=False)
    public_key = values.get("LANGFUSE_COPYME2AI_PUBLIC_KEY")
    secret_key = values.get("LANGFUSE_COPYME2AI_SECRET_KEY")
    if not public_key or not secret_key:
        raise ValueError("Memoir Langfuse credentials are missing from the credential file")
    port = values.get("LANGFUSE_PORT") or "3001"
    if not port.isdigit():
        raise ValueError("Invalid local Langfuse port")
    client = Langfuse(public_key=public_key, secret_key=secret_key,
                      host=f"http://127.0.0.1:{port}")
    if not client.auth_check():
        raise ValueError("Memoir Langfuse authentication failed")
    return client
