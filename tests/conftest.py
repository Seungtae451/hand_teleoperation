import pytest

from benchmark.simulation.build_model import build_model
from benchmark.simulation.robot_model import RobotModel


@pytest.fixture(scope="session")
def model_path(tmp_path_factory):
    return build_model(output=tmp_path_factory.mktemp("tesollo") / "dg5f_right.xml")


@pytest.fixture
def robot(model_path):
    return RobotModel(model_path)
