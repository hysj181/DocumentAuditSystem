from __future__ import annotations

import pytest
from real_batch_support import initialize_real_batch


@pytest.fixture(scope="session", autouse=True)
def real_batch_fixture(tmp_path_factory: pytest.TempPathFactory):
    """Build the real Word/PDF batch once for the whole test session."""

    root = tmp_path_factory.mktemp("real_batch")
    return initialize_real_batch(root)
