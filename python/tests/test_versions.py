import fefat
import fefat_app


def test_both_packages_carry_the_scaffold_version() -> None:
    assert fefat.__version__ == "0.0.1"
    assert fefat_app.__version__ == "0.0.1"
