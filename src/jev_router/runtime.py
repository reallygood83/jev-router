import os


_BLOCKED_NAMES = {
    "TYPESAFE_API_KEY",
    "JEV_EVIDENCE_KEY",
    "JEV_SCORER_KEY",
    "JEV_SCORER_ID",
}
_BLOCKED_PREFIXES = ("TYPESAFE_", "JEV_")


def _blocked(name):
    upper = str(name).upper()
    return upper in _BLOCKED_NAMES or upper.startswith(_BLOCKED_PREFIXES)


def provider_environment(command):
    del command
    return {name: value for name, value in os.environ.items() if not _blocked(name)}
