from datetime import datetime, timezone
from .analysis import ROUTES


def report(store):
    sections = {path: operation(store, {}) for path, operation in ROUTES.items()}
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'dataset_fingerprint': store.fingerprint(),
        'sections': sections,
    }
