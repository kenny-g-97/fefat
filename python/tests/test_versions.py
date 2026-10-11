import importlib.metadata

import fefat
import fefat_app


def test_both_packages_carry_the_scaffold_version() -> None:
    assert fefat.__version__ == "0.0.1"
    assert fefat_app.__version__ == "0.0.1"


def test_the_sdk_reports_the_engine_version_and_build() -> None:
    build = fefat.engine_info()

    assert build.version == "0.0.1"
    assert isinstance(build.profile, fefat.BuildProfile)


def test_each_package_reports_the_version_its_pyproject_declares() -> None:
    assert fefat.__version__ == importlib.metadata.version("fefat")
    assert fefat_app.__version__ == importlib.metadata.version("fefat-app")
