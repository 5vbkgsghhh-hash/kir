from __future__ import annotations

import pytest

from kukai.ai_protocol.project_v0 import create_project_state
from kukai.design_source.examples import make_tower_source


@pytest.fixture
def state3():
    return create_project_state(make_tower_source(n_floors=3))


@pytest.fixture
def state54():
    return create_project_state(make_tower_source(n_floors=54))
