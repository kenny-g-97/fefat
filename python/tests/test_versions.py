import fefat
import fefat_app


def test_both_packages_carry_the_scaffold_version() -> None:
    assert fefat.__version__ == "0.0.1"
    assert fefat_app.__version__ == "0.0.1"


def test_the_sdk_reports_the_engine_version_and_build() -> None:
    info = fefat.engine_info()

    assert info.version == "0.0.1"
    assert info.profile in {"debug", "release"}
