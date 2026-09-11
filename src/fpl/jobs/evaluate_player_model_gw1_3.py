"""Run the single preregistered GW1-3 diagnostic with no configurable model overrides."""

from fpl.config import repo_root
from fpl.validate.player_model_gw1_3_audit import run_audit


def main() -> None:
    run_audit(repo_root())


if __name__ == "__main__":
    main()
